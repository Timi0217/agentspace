"""
Skill cluster taxonomy for semantic tech stack matching.

Instead of exact string matching ("PyTorch" == "PyTorch"), we group related
technologies into clusters.  A candidate who has ANY skill in a cluster is
considered to have coverage of that cluster.

Used by:
  - calculate_match_score() for the tech-stack component
  - filter_candidates_for_role() for the must-have skill gate
"""

from typing import Dict, List, Optional, Set, Tuple
import re

# ---------------------------------------------------------------------------
# Cluster definitions
# ---------------------------------------------------------------------------
# Each cluster maps a canonical domain name → set of keywords/technologies.
# Keywords are stored LOWER-CASED.  Matching is case-insensitive.

SKILL_CLUSTERS: Dict[str, List[str]] = {
    # --- AI / ML ---
    "machine_learning": [
        "machine learning", "ml", "deep learning", "neural network",
        "neural networks", "model training", "scikit-learn", "sklearn",
        "xgboost", "lightgbm", "catboost", "gradient boosting",
        "random forest", "supervised learning", "unsupervised learning",
        "reinforcement learning",
    ],
    "pytorch": [
        "pytorch", "torch", "torchvision", "torchaudio",
    ],
    "tensorflow": [
        "tensorflow", "tf", "keras",
    ],
    "jax": [
        "jax", "flax", "optax",
    ],
    "llm": [
        "llm", "large language model", "language model", "gpt",
        "transformer", "transformers", "hugging face", "huggingface",
        "fine-tuning", "finetuning", "prompt engineering", "openai",
        "anthropic", "langchain", "llama", "mistral", "gemini",
    ],
    "rag": [
        "rag", "retrieval augmented generation", "retrieval-augmented",
    ],
    "nlp": [
        "nlp", "natural language processing", "spacy", "nltk",
        "text classification", "named entity recognition", "ner",
        "sentiment analysis", "tokenization",
    ],
    "computer_vision": [
        "computer vision", "cv", "opencv", "image recognition",
        "object detection", "yolo", "image segmentation", "ocr",
    ],
    "mlops": [
        "mlops", "mlflow", "kubeflow", "weights & biases", "wandb",
        "model serving", "model deployment", "feature store",
        "ml pipeline", "sagemaker", "vertex ai", "bentoml",
        "seldon", "triton", "onnx",
    ],
    "data_science": [
        "data science", "pandas", "numpy", "scipy", "matplotlib",
        "seaborn", "jupyter", "data analysis", "statistical",
        "statistics", "r language", "r programming",
    ],
    "vector_databases": [
        "vector database", "vector db", "pinecone", "weaviate",
        "chromadb", "chroma", "faiss", "milvus", "qdrant",
        "pgvector", "semantic search", "embeddings", "embedding",
    ],

    # --- Languages ---
    "python": ["python"],
    "javascript": ["javascript", "js"],
    "typescript": ["typescript", "ts"],
    "go": ["go", "golang"],
    "rust": ["rust"],
    "java": ["java"],
    "kotlin": ["kotlin"],
    "swift": ["swift"],
    "cpp": ["c++", "cpp"],
    "c_lang": ["c language", "c programming"],  # careful not to match "c" alone
    "ruby": ["ruby"],
    "php": ["php"],
    "scala": ["scala"],
    "elixir": ["elixir", "erlang"],
    "haskell": ["haskell"],
    "lua": ["lua"],
    "zig": ["zig"],
    "solidity": ["solidity"],

    # --- Frontend ---
    "react": ["react", "react.js", "reactjs", "next.js", "nextjs", "remix"],
    "vue": ["vue", "vue.js", "vuejs", "nuxt", "nuxt.js"],
    "angular": ["angular"],
    "svelte": ["svelte", "sveltekit"],
    "frontend": [
        "frontend", "front-end", "front end", "html", "css",
        "tailwind", "tailwindcss", "sass", "scss", "styled-components",
        "webpack", "vite", "esbuild",
    ],
    "mobile_dev": [
        "react native", "flutter", "ios", "android",
        "swiftui", "jetpack compose", "mobile development",
    ],

    # --- Backend ---
    "node": ["node", "node.js", "nodejs", "express", "express.js", "nestjs", "nest.js", "fastify"],
    "django": ["django", "django rest framework", "drf"],
    "fastapi": ["fastapi"],
    "flask": ["flask"],
    "rails": ["rails", "ruby on rails"],
    "spring": ["spring", "spring boot", "springboot"],
    "dotnet": [".net", "dotnet", "asp.net", "c#", "csharp"],

    # --- Data / Databases ---
    "postgresql": ["postgresql", "postgres", "pg"],
    "mysql": ["mysql", "mariadb"],
    "mongodb": ["mongodb", "mongo"],
    "redis": ["redis"],
    "elasticsearch": ["elasticsearch", "elastic", "opensearch"],
    "cassandra": ["cassandra", "scylladb"],
    "dynamodb": ["dynamodb"],
    "sql": ["sql", "database", "rdbms"],
    "graphql": ["graphql", "apollo graphql"],

    # --- Data Engineering ---
    "data_engineering": [
        "data engineering", "etl", "data pipeline", "data warehouse",
        "data lake", "data lakehouse", "dbt",
    ],
    "spark": ["spark", "pyspark", "apache spark"],
    "kafka": ["kafka", "apache kafka", "confluent"],
    "airflow": ["airflow", "apache airflow", "dagster", "prefect"],
    "big_data": [
        "big data", "hadoop", "hive", "presto", "trino",
        "snowflake", "bigquery", "redshift", "databricks", "delta lake",
    ],
    "streaming": [
        "streaming", "real-time data", "flink", "apache flink",
        "kinesis", "pulsar",
    ],

    # --- Cloud / Infra ---
    "aws": [
        "aws", "amazon web services", "ec2", "s3", "lambda",
        "ecs", "eks", "fargate", "cloudformation", "cdk",
    ],
    "gcp": [
        "gcp", "google cloud", "google cloud platform",
        "cloud run", "cloud functions", "gke",
    ],
    "azure": ["azure", "microsoft azure"],
    "docker": ["docker", "container", "containerization"],
    "kubernetes": ["kubernetes", "k8s", "helm", "kubectl"],
    "terraform": ["terraform", "infrastructure as code", "iac", "pulumi", "cloudformation"],
    "ci_cd": [
        "ci/cd", "cicd", "ci cd", "github actions", "gitlab ci",
        "jenkins", "circleci", "buildkite", "argo cd", "argocd",
    ],
    "linux": ["linux", "unix", "shell", "bash"],

    # --- Security ---
    "security": [
        "security", "cybersecurity", "infosec", "penetration testing",
        "vulnerability", "soc", "siem", "zero trust",
    ],
    "cryptography": [
        "cryptography", "encryption", "tls", "ssl", "pki",
    ],

    # --- Blockchain / Web3 ---
    "blockchain": [
        "blockchain", "web3", "smart contract", "ethereum",
        "defi", "nft", "dapp", "evm",
    ],

    # --- Systems / Low-level ---
    "systems": [
        "systems programming", "operating systems", "kernel",
        "embedded", "firmware", "real-time", "rtos",
    ],
    "distributed_systems": [
        "distributed systems", "consensus", "raft", "paxos",
        "microservices", "service mesh", "grpc", "protobuf",
    ],
    "compilers": [
        "compiler", "interpreter", "llvm", "ast",
        "parser", "lexer", "language design",
    ],
    "graphics": [
        "graphics", "rendering", "opengl", "vulkan", "webgl",
        "webgpu", "three.js", "game engine", "unity", "unreal",
        "shader", "gpu programming", "cuda",
    ],
}

# ---------------------------------------------------------------------------
# Reverse index: keyword -> set of cluster names
# Built once at import time for O(1) lookups.
# ---------------------------------------------------------------------------
_KEYWORD_TO_CLUSTERS: Dict[str, Set[str]] = {}

for _cluster_name, _keywords in SKILL_CLUSTERS.items():
    for _kw in _keywords:
        _kw_lower = _kw.lower()
        _KEYWORD_TO_CLUSTERS.setdefault(_kw_lower, set()).add(_cluster_name)


def _normalize_skill(skill: str) -> str:
    """Normalize a skill string for matching."""
    return skill.lower().strip().rstrip('.')


def get_clusters_for_skill(skill: str) -> Set[str]:
    """Return the set of cluster names that a single skill/keyword belongs to."""
    norm = _normalize_skill(skill)

    # Exact match first
    if norm in _KEYWORD_TO_CLUSTERS:
        return _KEYWORD_TO_CLUSTERS[norm]

    # Substring match: check if any keyword is contained in the skill
    # (e.g. "PyTorch Lightning" contains "pytorch")
    matches = set()
    for kw, clusters in _KEYWORD_TO_CLUSTERS.items():
        if len(kw) >= 3 and kw in norm:
            matches.update(clusters)

    return matches


def get_candidate_clusters(
    tech_stack: Optional[List[str]] = None,
    vibe_report: Optional[dict] = None,
    github_languages: Optional[List[str]] = None,
) -> Set[str]:
    """
    Compute the set of skill clusters a candidate covers.

    Sources (in order of richness):
    1. tech_stack — explicit technologies from VibeChekk analysis
    2. vibe_report.verified_skills — skills with evidence from GitHub projects
    3. vibe_report.trajectory_summary + project descriptions — free text scan
    4. github_languages — raw language detection from GitHub
    """
    clusters: Set[str] = set()

    # 1. tech_stack
    for skill in (tech_stack or []):
        clusters.update(get_clusters_for_skill(skill))

    # 2. vibe_report verified_skills
    if vibe_report:
        for vs in vibe_report.get('verified_skills', []):
            name = vs.get('name', '')
            if name:
                clusters.update(get_clusters_for_skill(name))
            # Also scan evidence text
            evidence = vs.get('evidence', '')
            if evidence:
                clusters.update(_scan_text_for_clusters(evidence))

        # 3. trajectory_summary
        summary = vibe_report.get('trajectory_summary', '')
        if summary:
            clusters.update(_scan_text_for_clusters(summary))

        # Scan top project descriptions
        for proj in vibe_report.get('top_projects', []):
            desc = proj.get('description', '')
            if desc:
                clusters.update(_scan_text_for_clusters(desc))
            # Project languages
            for lang in proj.get('languages', []):
                clusters.update(get_clusters_for_skill(lang))

    # 4. github_languages
    for lang in (github_languages or []):
        clusters.update(get_clusters_for_skill(lang))

    return clusters


def get_role_clusters(
    tech_stack: Optional[List[str]] = None,
    required_skills: Optional[List[str]] = None,
    jd_text: Optional[str] = None,
) -> Set[str]:
    """
    Compute the set of skill clusters a role requires.

    Sources:
    1. tech_stack — explicit technologies from parsed JD
    2. required_skills — skill descriptions from JD
    3. jd_text — scan full JD for additional cluster keywords
    """
    clusters: Set[str] = set()

    for skill in (tech_stack or []):
        clusters.update(get_clusters_for_skill(skill))

    for skill in (required_skills or []):
        clusters.update(_scan_text_for_clusters(skill))

    # Light scan of JD text (only the first 3000 chars to avoid noise)
    if jd_text:
        clusters.update(_scan_text_for_clusters(jd_text[:3000]))

    return clusters


def compute_cluster_overlap(
    candidate_clusters: Set[str],
    role_clusters: Set[str],
) -> Tuple[Set[str], Set[str], Set[str]]:
    """
    Returns (matched, missing, extra) cluster sets.
    """
    matched = candidate_clusters & role_clusters
    missing = role_clusters - candidate_clusters
    extra = candidate_clusters - role_clusters
    return matched, missing, extra


def _scan_text_for_clusters(text: str) -> Set[str]:
    """Scan free text for cluster keywords.  Returns matching cluster names."""
    if not text:
        return set()

    text_lower = text.lower()
    found: Set[str] = set()

    for kw, clusters in _KEYWORD_TO_CLUSTERS.items():
        # Only match keywords >= 3 chars to avoid false positives
        if len(kw) < 3:
            continue
        # Word boundary check for short keywords to reduce false positives
        if len(kw) <= 4:
            if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
                found.update(clusters)
        else:
            if kw in text_lower:
                found.update(clusters)

    return found
