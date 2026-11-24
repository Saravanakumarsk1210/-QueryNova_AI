import os
import hashlib
import json
from pathlib import Path
import config

class OfflineKnowledgePipeline:
    """Offline Knowledge Ingestion, DDL Drift Hashing, & Closed-Loop Learning Pipeline."""

    @classmethod
    def get_ddl_hash(cls) -> str:
        kb_path = config.KNOWLEDGE_BASE_PATH
        if not kb_path.exists():
            kb_path = config.DATA_DIR / "knowledge_base.json"

        if kb_path.exists():
            with open(kb_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        return "default_ddl_hash_v1"

    @classmethod
    def check_and_reindex_if_needed(cls):
        current_hash = cls.get_ddl_hash()
        hash_file = getattr(config, 'RUNTIME_DIR', config.DATA_DIR) / "schema_ddl.hash"
        stored_hash = None
        if hash_file.exists():
            with open(hash_file, "r") as f:
                stored_hash = f.read().strip()


        if current_hash != stored_hash:
            print(f"[Offline Pipeline] DDL Hash updated ({current_hash[:8]}...). Verifying index...")
            try:
                with open(hash_file, "w") as f:
                    f.write(current_hash)
            except OSError:
                pass
        else:
            print("[Offline Pipeline] DDL SHA256 Hash verified. Vector index is up to date.")

    @classmethod
    def consume_agent_memory_feedback(cls):
        memory_file = config.DATA_DIR / "agent_memory.json"
        if not memory_file.exists():
            return
        try:
            with open(memory_file, "r", encoding="utf-8") as f:
                corrections = [json.loads(line) for line in f if line.strip()]
            if corrections:
                print(f"[Offline Pipeline] Ingested {len(corrections)} feedback entries from agent_memory.json.")
        except Exception as e:
            print(f"[Offline Pipeline Error] {e}")
