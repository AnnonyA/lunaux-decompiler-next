# LunaUX 0.18 differential benchmark

Version 0.18 starts the measurable-quality phase of LunaUX. The benchmark runs the same bytecode corpus through LunaUX and any configured external decompiler, saves every emitted source file, and produces one machine-readable JSON report.

## Goals

The first 0.18 milestone measures four facts without subjective claims:

1. whether a backend returned non-empty output;
2. whether it crashed, failed, or timed out;
3. how long each case took;
4. the exact SHA-256 of every emitted artifact.

Syntax validation, recompilation, semantic comparison, and readability scoring will be added as separate validators. Keeping the raw execution layer small makes the baseline reproducible before those scores are introduced.

## Corpus manifest

```json
{
  "schema_version": 1,
  "cases": [
    {
      "id": "closures-captures-o2",
      "bytecode": "fixtures/closures-captures-o2.luac",
      "source": "sources/closures-captures.luau",
      "optimization": "O2",
      "tags": ["closure", "capture", "optimized"]
    }
  ]
}
```

Paths are resolved relative to the manifest and may not escape its directory. Case IDs must be unique.

## External backends

External tools are executed without a shell. Each command must contain `{input}`. File-producing tools must also contain `{output}`.

```json
{
  "schema_version": 1,
  "backends": [
    {
      "name": "medal",
      "version": "pinned-commit",
      "command": ["medal", "decompile", "{input}", "--output", "{output}"],
      "output": "file"
    }
  ]
}
```

Pin every competitor to a commit or release. A moving `latest` target makes benchmark changes impossible to attribute.

## Run

```bash
python scripts/run_benchmarks.py benchmarks/manifest.json \
  --external-backends benchmarks/backends.json \
  --output benchmark-report.json \
  --artifacts benchmark-artifacts \
  --timeout 30
```

The active LunaUX engine is selected through the normal environment configuration. External processes receive an independent timeout for every case.

## 0.18 release gates

The final 0.18 release should not claim to beat Medal until the repository includes:

- a versioned public corpus with real compiler output at `-O0`, `-O1`, and `-O2`;
- syntax and recompilation validators using a pinned Luau toolchain;
- semantic fixtures with deterministic expected behavior;
- a competitor matrix pinned to exact revisions;
- a published report where LunaUX wins the agreed correctness score without regressing stability.
