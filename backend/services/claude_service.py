"""
LLM 服务 - 多 Provider 架构
支持多 Provider 架构（文本 + 多模态视觉模型）
"""
from openai import OpenAI
import json
import time
import config
from models.database import ConversationDAO

# 全局模型状态（跨实例共享）
_current_global_model = {"id": None}


def get_current_model() -> str:
    """获取全局当前模型 ID"""
    return _current_global_model["id"] or config.LLM_MODEL


def set_global_model(model_id: str) -> bool:
    """设置全局模型"""
    global _current_global_model
    _current_global_model["id"] = model_id
    return True


class LLMService:
    """多 Provider LLM 路由器，支持模型切换和 RAG"""

    def __init__(self):
        self._clients = {}
        self._models = {}
        _first_text = None
        _first_multimodal = None

        # 优先从 MODEL_PROVIDERS 构建，否则回退到旧式 env var
        providers = config.MODEL_PROVIDERS if config.MODEL_PROVIDERS else []
        if not providers:
            # 回退：从旧式 env var 构建
            if config.LLM_API_KEY:
                providers.append({
                    "name": "DeepSeek V4 Flash",
                    "base_url": config.LLM_BASE_URL,
                    "api_key": config.LLM_API_KEY,
                    "model": config.LLM_MODEL,
                    "type": "text"
                })
            if config.MULTIMODAL_API_KEY:
                providers.append({
                    "name": "智谱 GLM-4.6V",
                    "base_url": config.MULTIMODAL_BASE_URL,
                    "api_key": config.MULTIMODAL_API_KEY,
                    "model": config.MULTIMODAL_MODEL,
                    "type": "multimodal"
                })

        for p in providers:
            pid = p.get("name", "").lower().replace(" ", "-")
            if not pid:
                continue
            api_key = p.get("api_key", "")
            if not api_key:
                continue
            self._clients[pid] = OpenAI(
                api_key=api_key,
                base_url=p.get("base_url", ""),
            )
            ptype = p.get("type", "text")
            self._models[pid] = {
                "id": pid,
                "name": p.get("name", pid),
                "type": ptype,
                "available": True,
                "model": p.get("model", ""),
                "max_tokens": config.LLM_MAX_TOKENS if ptype == "text" else 4096,
            }
            if ptype == "text" and _first_text is None:
                _first_text = pid
            if ptype == "multimodal" and _first_multimodal is None:
                _first_multimodal = pid

        self._first_text = _first_text or "deepseek-v4-flash"
        self._first_multimodal = _first_multimodal or "glm-4.6v"

        self.current_model = config.LLM_MODEL
        self.model = config.LLM_MODEL
        self.max_tokens = config.LLM_MAX_TOKENS

        self.system_prompt = """你是一个专为AI产品经理设计的个人学习助手。

## 身份
- 精通PM方法论（用户故事、优先级矩阵、MVP设计）
- 熟悉AI产品设计（Prompt Engineering、模型评估、数据飞轮）
- 了解技术底层（大模型原理、RAG、Fine-tuning）

## 回答风格
- 直接、有洞察，不废话
- 用PM语言组织回答（价值主张、用户场景、权衡取舍）
- 技术概念用类比解释
- 可以使用 Markdown 格式让内容更清晰（如列表、表格、加粗重点）
- 回答要有对话感，像和同事聊天一样自然，不要像写文档

## 当前任务
基于用户上传的学习资料，回答问题。如果提供了上下文片段，请：
1. 理解和消化资料内容，用自己的话总结回答
2. 不要直接复制粘贴资料原文
3. 提取关键信息，用清晰的结构组织
4. 如果资料中没有相关信息，可以基于你的知识补充，但需明确标注"（补充知识）"

## 记忆上下文
你会在对话中记住用户的困惑点，主动识别薄弱知识点。
"""

        self.quiz_prompt = """你是一个专业的学习测评出题系统。

## 规则
1. 严格基于提供的文档内容出题，不超出文档范围
2. 题目必须能检验对知识点的真实理解，而非死记硬背
3. 每道题标注所属知识点
4. 选择题必须有且仅有一个正确答案
5. 简答题要考察综合理解能力

## 输出格式
严格输出JSON，不要任何额外说明。
"""

        self.judge_prompt = """你是一个专业的学习测评评判系统。

## 规则
1. 严格评判答案是否正确
2. 选择题/判断题：精确匹配或语义等价算对
3. 简答题：基于核心概念是否到位给分（0/0.5/1.0）
4. 给出简短的反馈说明
5. 识别该题对应知识点的掌握程度

## 输出格式
严格输出JSON，不要任何额外说明。
"""

    def _resolve_model(self) -> str:
        """将内部模型 ID 解析为 API 实际模型名"""
        mid = get_current_model()
        cfg = self._models.get(mid, {})
        return cfg.get("model", mid)

    @property
    def client(self):
        """返回当前模型对应的 OpenAI client（使用全局状态）"""
        model_id = get_current_model()
        return self._clients.get(model_id) or next(iter(self._clients.values()), None)

    def get_available_models(self) -> list:
        """返回可用模型列表"""
        models = list(self._models.values())
        current = get_current_model()
        for m in models:
            m["is_current"] = (m["id"] == current)
        return models

    def set_model(self, model_id: str) -> bool:
        """切换模型，返回是否成功"""
        if model_id in self._clients:
            self.current_model = model_id
            cfg = self._models[model_id]
            self.model = cfg["model"]
            self.max_tokens = cfg["max_tokens"]
            set_global_model(model_id)
            print(f"[LLM] 模型切换至: {model_id}")
            return True
        return False

    def _call(self, messages: list, max_tokens: int = None, retries: int = 3) -> str:
        """统一调用入口，网络异常自动重试"""
        import httpx
        model = self._resolve_model()
        client = self.client
        tokens = max_tokens or self.max_tokens
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    max_tokens=tokens,
                    messages=messages,
                )
                return response.choices[0].message.content
            except (httpx.ConnectError, httpx.ReadTimeout, ConnectionError, OSError) as e:
                last_err = e
                if attempt < retries:
                    wait = attempt * 2  # 2s, 4s, 6s
                    print(f"[LLM] 网络异常，{wait}秒后第{attempt+1}次重试... ({e})")
                    time.sleep(wait)
                continue
            except Exception as e:
                raise RuntimeError(f"LLM API 错误: {str(e)}")
        raise RuntimeError(f"LLM API 连接失败（已重试{retries}次）: {last_err}")

    def chat(self, conversation_id: int, user_message: str, context_chunks: list = None, user_id: int = None) -> str:
        """
        发送消息并获取回复
        """
        messages = ConversationDAO.get_messages(conversation_id)
        message_list = [{"role": m["role"], "content": m["content"]} for m in messages]

        enhanced_content = user_message
        if context_chunks:
            context_text = "\n\n---\n\n".join([
                f"[资料片段 {i+1}]\n{chunk}" for i, chunk in enumerate(context_chunks)
            ])
            enhanced_content = (
                f"以下是与用户问题相关的学习资料片段，请优先基于这些内容回答：\n\n"
                f"{context_text}\n\n---\n\n"
                f"用户问题：{user_message}"
            )

        full_messages = [{"role": "system", "content": self.system_prompt}]
        full_messages.extend(message_list)
        full_messages.append({"role": "user", "content": enhanced_content})

        try:
            assistant_reply = self._call(full_messages)

            ConversationDAO.add_message(conversation_id, "user", user_message, user_id=user_id)
            ConversationDAO.add_message(
                conversation_id, "assistant", assistant_reply,
                source_chunks=context_chunks, user_id=user_id
            )
            return assistant_reply

        except RuntimeError as e:
            ConversationDAO.add_message(conversation_id, "assistant", str(e), user_id=user_id)
            return str(e)

    def chat_stream(self, conversation_id: int, user_message: str, context_chunks: list = None, user_id: int = None):
        """
        流式对话 - 返回生成器逐 chunk 输出
        """
        import httpx

        messages = ConversationDAO.get_messages(conversation_id)
        message_list = [{"role": m["role"], "content": m["content"]} for m in messages]

        enhanced_content = user_message
        if context_chunks:
            context_text = "\n\n---\n\n".join([
                f"[资料片段 {i+1}]\n{chunk}" for i, chunk in enumerate(context_chunks)
            ])
            enhanced_content = (
                f"以下是与用户问题相关的学习资料片段，请优先基于这些内容回答：\n\n"
                f"{context_text}\n\n---\n\n"
                f"用户问题：{user_message}"
            )

        full_messages = [{"role": "system", "content": self.system_prompt}]
        full_messages.extend(message_list)
        full_messages.append({"role": "user", "content": enhanced_content})

        # 存储用户消息
        ConversationDAO.add_message(conversation_id, "user", user_message, user_id=user_id)

        full_reply = ""
        try:
            response = self.client.chat.completions.create(
                model=self._resolve_model(),
                max_tokens=self.max_tokens,
                messages=full_messages,
                stream=True
            )
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_reply += content
                    yield content
        except (httpx.ConnectError, httpx.ReadTimeout, ConnectionError, OSError) as e:
            error_msg = f"网络连接失败: {e}"
            full_reply = error_msg
            yield error_msg
        except Exception as e:
            error_msg = f"错误: {str(e)}"
            full_reply = error_msg
            yield error_msg

        # 存储 AI 回复
        ConversationDAO.add_message(
            conversation_id, "assistant", full_reply,
            source_chunks=context_chunks, user_id=user_id
        )

    def stream_generate(self, system_prompt: str, user_message: str, max_tokens: int = None):
        """
        通用流式生成 — 不绑定对话/不写DB，纯 generator
        用于资讯综合报告等非对话场景的流式输出
        """
        import httpx

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        try:
            response = self.client.chat.completions.create(
                model=self._resolve_model(),
                max_tokens=max_tokens or self.max_tokens,
                messages=messages,
                stream=True
            )
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except (httpx.ConnectError, httpx.ReadTimeout, ConnectionError, OSError) as e:
            yield f"网络连接失败: {e}"
        except Exception as e:
            yield f"错误: {str(e)}"

    def chat_with_image(self, image_base64: str, question: str, context: str = "") -> str:
        """
        多模态对话 — 自动路由到多模态视觉模型

        Args:
            image_base64: Base64 编码的图片
            question: 用户问题
            context: 可选的文本上下文

        Returns:
            模型回答文本
        """
        # 自动切换到多模态模型
        multimodal_id = self._first_multimodal
        if multimodal_id not in self._clients:
            return "错误：未配置多模态模型，无法使用多模态功能。请在设置中添加多模态类型的模型提供商。"

        prev_model = self.current_model
        self.set_model(multimodal_id)

        try:
            content = [{"type": "text", "text": question or "请描述这张图片的内容"}]
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
            })
            if context:
                content.insert(0, {"type": "text", "text": f"参考上下文：{context}"})

            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": content}
            ]

            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=messages
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"多模态分析失败: {str(e)}"
        finally:
            self.set_model(prev_model)

    def generate_practice_questions(self, topic: str, context: str = "", count: int = 5, difficulty: str = "mixed") -> str:
        """生成练习题"""
        context_section = ""
        if context:
            context_section = "学习资料内容：\n" + context
        prompt = f"""基于以下学习内容，生成{count}道练习题。

主题：{topic}
难度：{difficulty}

{context_section}

要求：
1. 题型混合：选择题、简答题、判断题
2. 每题附带答案和解析
3. 用PM思维设计题目（场景化、应用导向）
4. 标注考查的知识点

输出JSON格式：
{{
  "questions": [
    {{
      "type": "choice|short_answer|true_false",
      "question": "题目内容",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "answer": "正确答案",
      "explanation": "解析",
      "knowledge_point": "考查的知识点"
    }}
  ]
}}

只输出JSON，不要额外说明。"""

        try:
            return self._call(
                [{"role": "system", "content": self.system_prompt},
                 {"role": "user", "content": prompt}],
                max_tokens=4096
            )
        except RuntimeError as e:
            return json.dumps({"error": str(e)})

    def generate_assessment(self, document_content: str, question_count: int = 8) -> dict:
        """
        基于文档内容生成测评题目

        Returns:
            {"questions": [{type, question, options, answer, explanation, knowledge_point, difficulty}, ...]}
        """
        import math
        n = question_count
        # 动态题型配比：25% 判断 + 50% 选择 + 剩余简答
        tf_count = max(1, math.floor(n * 0.25))
        choice_count = max(1, math.floor(n * 0.5))
        sa_count = n - tf_count - choice_count

        # 动态难度配比：25% 简单 + 50% 中等 + 剩余较难
        easy_n = max(0, math.floor(n * 0.25))
        medium_n = max(0, math.floor(n * 0.5))
        hard_n = n - easy_n - medium_n

        prompt = f"""基于以下文档内容，生成{n}道测评题。

要求：
- 题型分布：{tf_count}道判断题 + {choice_count}道单选题 + {sa_count}道简答题
- 难度分布：{easy_n}简单 + {medium_n}中等 + {hard_n}较难
- 每道题必须对应文档中的一个具体知识点
- 选择题选项4个，正确答案写选项字母（如"A"）
- 判断题答案写"正确"或"错误"
- 简答题答案写核心要点（不超过50字）

文档内容：
{document_content[:6000]}

输出JSON格式：
{{
  "questions": [
    {{
      "type": "choice",
      "question": "题目内容",
      "options": {{"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"}},
      "answer": "A",
      "explanation": "解析说明",
      "knowledge_point": "对应知识点名称",
      "difficulty": "easy"
    }},
    {{
      "type": "true_false",
      "question": "题目内容",
      "answer": "正确",
      "explanation": "解析说明",
      "knowledge_point": "对应知识点名称",
      "difficulty": "medium"
    }},
    {{
      "type": "short_answer",
      "question": "题目内容",
      "answer": "核心要点",
      "explanation": "评分标准",
      "knowledge_point": "对应知识点名称",
      "difficulty": "hard"
    }}
  ]
}}

只输出JSON，不要任何其他内容。"""

        try:
            raw = self._call(
                [{"role": "system", "content": self.quiz_prompt},
                 {"role": "user", "content": prompt}],
                max_tokens=4096
            )
            # 提取 JSON
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                raw = raw.rsplit("```", 1)[0] if "```" in raw else raw
            return json.loads(raw)
        except (json.JSONDecodeError, RuntimeError) as e:
            return {"error": str(e)}

    def _clean_json(self, raw: str) -> str:
        """清洗 LLM 输出，尽力提取有效 JSON"""
        raw = raw.strip()
        # 移除 markdown 代码块
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            raw = raw.rsplit("```", 1)[0] if "```" in raw else raw
            raw = raw.strip()
        # 找到首尾 { } 配对
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start:end+1]
        # 补全缺失的 }
        open_braces = raw.count("{") - raw.count("}")
        if open_braces > 0:
            raw += "}" * open_braces
        return raw

    def _local_judge_fallback(self, questions: list, answers: list) -> dict:
        """本地规则评判 — LLM 不可用时的兜底方案"""
        results = []
        for q, a in zip(questions, answers):
            q_type = q.get("question_type", "choice")
            correct = str(q.get("correct_answer", "")).strip()
            user = str(a.get("user_answer", "")).strip()
            kp = q.get("knowledge_point", "") or "综合"
            idx = a.get("question_index", answers.index(a))

            if q_type in ("choice", "multi_choice", "true_false"):
                # 选择题/判断题：精确比对
                is_correct = (user.upper() == correct.upper())
                score = 1.0 if is_correct else 0.0
                feedback = "回答正确" if is_correct else f"正确答案是 {correct}"
                mastery = "mastered" if is_correct else "weak"
            else:
                # 简答题：默认 0.5 分，标注人工复核
                is_correct = False
                score = 0.5
                feedback = "简答题需人工复核（系统兜底评分）"
                mastery = "familiar"

            results.append({
                "question_index": idx,
                "is_correct": is_correct,
                "score": score,
                "feedback": feedback,
                "knowledge_point": kp,
                "mastery_level": mastery
            })
        return {"results": results}

    def judge_answers(self, questions: list, answers: list) -> dict:
        """
        批量评判用户答案 — LLM 优先，失败回退本地规则

        Args:
            questions: [{question_type, question_text, options, correct_answer, ...}, ...]
            answers:   [{question_index, user_answer}, ...]

        Returns:
            {"results": [{question_index, is_correct, score, feedback, knowledge_point, mastery_level}, ...]}
        """
        import concurrent.futures

        # 构建评判请求
        qa_pairs = []
        for q, a in zip(questions, answers):
            entry = {
                "index": a.get("question_index", answers.index(a)),
                "type": q["question_type"],
                "question": q["question_text"],
                "correct_answer": q["correct_answer"],
                "user_answer": a.get("user_answer", ""),
                "knowledge_point": q.get("knowledge_point", "")
            }
            if q.get("options"):
                try:
                    entry["options"] = json.loads(q["options"]) if isinstance(q["options"], str) else q["options"]
                except:
                    entry["options"] = q["options"]
            qa_pairs.append(entry)

        prompt = f"""请评判以下用户的测评答案。

{json.dumps(qa_pairs, ensure_ascii=False, indent=2)}

评判要求：
- choice/multi_choice 类型：选项字母完全匹配算对，is_correct 为 true/false，score 为 1.0 或 0.0
- true_false 类型：A=正确，B=错误。选项字母匹配算对，is_correct 为 true/false，score 为 1.0 或 0.0
- short_answer 类型：核心概念到位给 1.0，部分正确给 0.5，完全偏离给 0.0
- feedback 用一句话说明对错原因
- mastery_level 基于该题结果判断该知识点掌握度：correct→"mastered"，partial→"familiar"，wrong→"weak"

输出JSON格式：
{{
  "results": [
    {{
      "question_index": 0,
      "is_correct": true,
      "score": 1.0,
      "feedback": "回答正确",
      "knowledge_point": "知识点名称",
      "mastery_level": "mastered"
    }}
  ]
}}

只输出JSON，不要任何其他内容。"""

        # 尝试 LLM 评判（10s 超时）
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    self._call,
                    [{"role": "system", "content": self.judge_prompt},
                     {"role": "user", "content": prompt}],
                    4096,
                    1  # retries=1，快速失败
                )
                raw = future.result(timeout=20)
            raw = self._clean_json(raw)
            result = json.loads(raw)
            if "results" in result:
                return result
        except (json.JSONDecodeError, RuntimeError, concurrent.futures.TimeoutError, Exception):
            pass

        # 回退本地规则
        print("[LLM] 评判失败或超时，回退本地规则评判")
        return self._local_judge_fallback(questions, answers)

    def generate_weekly_report(self, study_stats: dict, weak_points: list, recent_topics: list) -> str:
        """生成周报 Markdown 内容"""
        import math

        total_time = study_stats.get("total_time", 0)
        total_questions = study_stats.get("total_questions", 0)
        docs_studied = study_stats.get("docs_studied", 0)
        hours = math.floor(total_time / 60)
        mins = total_time % 60

        weak_text = ""
        if weak_points:
            weak_text = "\n".join([
                f"- {p.get('topic', p.get('name', '未知'))}：掌握度 {p.get('mastery_rate', p.get('mastery_level', '未知'))}"
                for p in weak_points[:8]
            ])
        else:
            weak_text = "- 暂无数据，继续学习后系统会自动识别"

        topics_text = "\n".join([f"- {t}" for t in recent_topics]) if recent_topics else "- 本周暂无新接触的知识点"

        prompt = f"""你是一个专业的学习分析师，请根据以下数据生成一份结构清晰的周学习报告。

## 学习数据
- 总学习时长：{hours}小时{mins}分钟
- 提问数量：{total_questions}次
- 学习文档数：{docs_studied}篇
- 薄弱知识点：
{weak_text}
- 近期接触的知识点：
{topics_text}

## 报告要求
1. 整体评价：用2-3句话总结本周学习状态
2. 学习亮点：列出1-3个值得肯定的方面
3. 薄弱环节：针对薄弱知识点给出具体改进建议
4. 下周计划：基于薄弱环节推荐学习方向（2-3条）
5. 用 Markdown 格式输出，语气鼓励但客观

请直接输出报告内容，不要加标题"周学习报告"。"""

        return self._call(
            [{"role": "system", "content": "你是专业的学习分析师，擅长基于学习数据生成洞察报告。用 Markdown 格式输出。"},
             {"role": "user", "content": prompt}],
            max_tokens=2048
        )

    def extract_knowledge_points(self, document_content: str) -> list:
        """
        从文档中提取知识点大纲

        Returns:
            [{"name": "知识点名称", "summary": "一句话描述"}, ...]
        """
        prompt = f"""分析以下文档内容，提取所有核心知识点。

要求：
- 每个知识点一个独立的概念或技能点
- 知识点粒度适中（一个章节下 3-8 个）
- 用简洁的名称概括
- 按文档中的出现顺序排列

文档内容：
{document_content[:5000]}

输出JSON格式：
{{"knowledge_points": [{{"name": "知识点名称", "summary": "一句话描述"}}]}}

只输出JSON，不要任何其他内容。"""

        try:
            raw = self._call(
                [{"role": "system", "content": "你是一个专业的课程分析师，擅长从学习资料中提取结构化知识点。只输出JSON。"},
                 {"role": "user", "content": prompt}],
                max_tokens=2048
            )
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                raw = raw.rsplit("```", 1)[0] if "```" in raw else raw
            return json.loads(raw).get("knowledge_points", [])
        except (json.JSONDecodeError, RuntimeError, KeyError):
            return []


# 兼容旧代码的别名
ClaudeService = LLMService
