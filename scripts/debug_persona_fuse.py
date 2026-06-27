"""Debug persona question generation."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import load_personas
from src.graph.nodes.exam import build_persona_exam_input
from src.graph.subgraphs.persona_exam.nodes import _format_chunks_for_prompt, rag_retrieve
from src.models.llm_factory import persona_llm
from src.models.router import llm_runtime_info
from src.config import get_settings
from src.tools.json_utils import extract_json, llm_content_to_str

out_dir = Path("outputs/k8s-local-001")
chunks = json.loads((out_dir / "raw_chunks.json").read_text(encoding="utf-8"))
material = (out_dir / "study_material.md").read_text(encoding="utf-8")
parent = {
    "study_material": material,
    "raw_chunks": chunks[:30],
    "weak_topics": ["Pod"],
    "macro_iter": 6,
}
persona = load_personas()[0]
state = build_persona_exam_input(parent, persona, 0)
state.update(rag_retrieve(state))
count = state.get("questions_target", 10)
rag_ctx = _format_chunks_for_prompt(state.get("retrieved_chunks") or [])

print("router:", llm_runtime_info(get_settings()))

prompt = f"""You are {state.get('persona_name')}. Generate {count} exam questions.
Output JSON array only:
[{{"question": "...", "evidence_refs": ["chunk_id"], "topic_tag": "..."}}]

Material:
{material[:4000]}

RAG:
{rag_ctx[:2000]}
"""

llm = persona_llm()
resp = llm.invoke([SystemMessage(content="JSON only"), HumanMessage(content=prompt)])
text = llm_content_to_str(resp.content)
print("RAW LEN:", len(text))
print("RAW HEAD:\n", text[:2000])
try:
    data = extract_json(resp.content)
    print("PARSED:", type(data), "len:", len(data) if isinstance(data, list) else data)
except Exception as exc:
    print("PARSE ERR:", exc)
