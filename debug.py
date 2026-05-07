# import chromadb
# from chromadb.config import Settings

# client = chromadb.PersistentClient(
#       path="./data/vector_db_test",
#       settings=Settings(anonymized_telemetry=False)
#   )
# print("ChromaDB 初始化成功")

from huggingface_hub import snapshot_download

  # 中文模型（推荐）
snapshot_download(
      repo_id="BAAI/bge-small-zh-v1.5",
      local_dir=r"D:\BaiduNetdiskDownload\project\ai-learning-assistant\embedding_model\bge-large-zh-v1.5"
  )
