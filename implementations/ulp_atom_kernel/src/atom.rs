use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct Region(pub String);

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum AtomKind {
    Prefill,
    Decode,
    Inference,
    Embedding,
    FineTune,
}

impl AtomKind {
    /// Whether this kind uses decode-phase routing rules
    /// (latency-sensitive, KV-locality-heavy).
    pub fn is_decode_phase(&self) -> bool {
        matches!(self, AtomKind::Decode)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComputeAtom {
    pub id: String,
    pub kind: AtomKind,
    pub region: Region,
    pub model_id: String,
    pub shard_count: u32,
}
