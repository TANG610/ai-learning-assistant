"""
Full end-to-end test: MediaCrawler douyin video -> ASR -> LLM structured extraction.
"""
import sys, os, json, time
from pathlib import Path

# Add project root and backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

# --- 1. Get video metadata ---
video_id = '7635260133824451045'
jsonl_path = 'D:/BaiduNetdiskDownload/project/MediaCrawler/data/douyin/jsonl/search_contents_2026-05-19.jsonl'
video_meta = {}
with open(jsonl_path, 'r', encoding='utf-8') as f:
    for line in f:
        d = json.loads(line)
        if d.get('aweme_id') == video_id:
            video_meta = d
            break

title = video_meta.get('title', '在读学生AI时代最应该做的两件事情')
desc = video_meta.get('desc', '')
tags = video_meta.get('tag_list', []) or ['AI', '大学生', '研究生', '经验分享']

print(f'Title: {title[:100]}')
print(f'Tags: {tags}')
print()

# --- 2. Run ASR ---
from backend.services.transcription_service import TranscriptionService

video_path = 'data/asr_douyin_test/douyin_test_video.mp4'
assert os.path.isfile(video_path), f"Video not found: {video_path}"

print('Running ASR...')
t0 = time.time()
result = TranscriptionService.transcribe(video_path)
print(f'ASR: {len(result["text"])} chars, {len(result["segments"])} segments, {time.time()-t0:.1f}s')

# --- 3. Quality gate ---
MIN_CHARS = 30
assert len(result['text']) >= MIN_CHARS, f'FAIL: quality gate ({len(result["text"])} < {MIN_CHARS})'
print('Quality gate: PASS')
print()

# --- 4. LLM structured extraction ---
from backend.services.claude_service import LLMService

def _fmt_ts(seconds):
    seconds = max(0, int(seconds or 0))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'{hours}:{minutes:02d}:{secs:02d}'
    return f'{minutes}:{secs:02d}'

segments = result['segments'][:80]
segment_text = '\n'.join(
    f'[{_fmt_ts(seg.get("start", 0))}] {str(seg.get("text", "")).strip()}'
    for seg in segments if str(seg.get('text', '')).strip()
)

llm = LLMService()
prompt = f"""请把下面的短视频口播内容做结构化提取。

标题：{title}
视频描述：{desc or "无"}
标签：{", ".join(tags or []) or "无"}

完整文字稿：
{result["text"][:6000]}

带时间戳片段：
{segment_text[:6000] or "无"}

要求：
1. summary 用 3 句话概括核心内容。
2. structure 提取 3-6 个核心观点，每个观点包含 point、evidence、timestamp。timestamp 优先使用上方片段里的时间，如 "0:30"。
3. key_takeaways 给出 3-5 条可执行/可记忆的要点。
4. topics 给出 3-5 个中文话题标签。
5. 只输出 JSON，不要 Markdown 代码块。

输出 JSON 格式：
{{"summary":"3句话核心概括","structure":[{{"point":"核心观点","evidence":"论据/案例","timestamp":"0:30"}}],"key_takeaways":["要点1"],"topics":["话题1"]}}"""

print('Running LLM structured extraction...')
t0 = time.time()
raw = llm._call(
    [
        {'role': 'system', 'content': '你是视频内容分析助手，擅长把口播文字稿整理成可检索的结构化知识。只输出 JSON。'},
        {'role': 'user', 'content': prompt},
    ],
    max_tokens=2048,
)
raw = raw.strip()
if raw.startswith('```'):
    lines = raw.split('\n')
    raw = '\n'.join(lines[1:]) if len(lines) > 1 else raw[3:]
    if raw.endswith('```'):
        raw = raw[:-3]
    raw = raw.strip()

structured = json.loads(raw)
print(f'LLM: {time.time()-t0:.1f}s')

# --- 5. Output full results ---
print()
print('=' * 70)
print('FULL ASR + LLM PIPELINE RESULTS')
print('=' * 70)

print(f'\n--- 摘要 ---')
print(structured.get('summary', 'N/A'))

print(f'\n--- 核心观点 ---')
for i, s in enumerate(structured.get('structure', []), 1):
    ts = s.get('timestamp', '?')
    point = s.get('point', '?')
    evidence = s.get('evidence', '')
    print(f'  {i}. [{ts}] {point}')
    if evidence:
        print(f'     论据: {evidence[:150]}')

print(f'\n--- 行动要点 ---')
for i, kt in enumerate(structured.get('key_takeaways', []), 1):
    print(f'  {i}. {kt}')

print(f'\n--- 话题标签 ---')
print(f'  {structured.get("topics", [])}')

print()
print('=' * 70)
print('Pipeline verification summary:')
print(f'  Video preserved after ASR: {os.path.exists(video_path)}')
print(f'  ASR transcript: {len(result["text"])} chars, {len(result["segments"])} segments')
print(f'  Quality gate (>=30 chars): PASSED')
print(f'  LLM structured extraction: COMPLETE')
print(f'  Summary: {len(structured.get("summary", ""))} chars')
print(f'  Structure points: {len(structured.get("structure", []))}')
print(f'  Takeaways: {len(structured.get("key_takeaways", []))}')
print(f'  Topics: {len(structured.get("topics", []))}')
print('=' * 70)
