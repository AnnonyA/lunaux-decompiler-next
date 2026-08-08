# LunaUX 0.18 differential benchmark

LunaUX 0.18 replaces feature-count claims with a public, reproducible comparison. Every backend receives the same source families, optimization/debug matrix, scoring contract, and all bytecode generations it can realistically process.

## Pinned inputs

`benchmarks/pins.json` fixes every tool to exact revisions:

- Luau v3 compiler: commit `3ecd3a82abe6682988112cd6eb7326a67ebbc47f`;
- Luau v6 compiler: commit `a251bc68a2b70212e53941fd541d16ce523a1e01`;
- current Luau v11 compiler/runtime/validator: commit `8f33df910d790c1321a20028af8d8134fa3e0334`;
- Medal: commit `92a4e03bef0d3c2bb0511bdba6c5f95b1df96003`;
- Unluau: commit `f89e03a560f535eb19f11e89a6aadec636d2a8f5`.

The three Luau generations are intentional. The pinned Medal implementation accepts serialized bytecode versions 4–6, while modern Luau emits version 11. A single modern corpus would therefore measure format incompatibility instead of decompiler quality. The balanced corpus includes v3 for older Unluau coverage, v6 for Medal, and v11 for current LunaUX behavior.

Medal requires unstable Rust features and did not publish a dependency lock at the pinned commit. The repository therefore records Rust 1.87.0, enables the feature gate with `RUSTC_BOOTSTRAP=1`, and stores the exact resolved `Cargo.lock` as `benchmarks/medal-Cargo.lock.gz.b64`. The installer verifies its decompressed SHA-256 before invoking Cargo with `--locked`. Medal's source is not patched.

`python scripts/install_benchmark_tools.py --include-unluau` verifies every checkout before building it and writes `toolchain.json`, `compilers.json`, and `backends.json`. No backend is invoked through a shell.

## Public corpus

`python scripts/generate_benchmark_corpus.py` creates source and bytecode deterministically. The release matrix contains:

- 16 semantic program families;
- 8 deterministic seeds per family;
- compiler generations producing bytecode v3, v6, and v11;
- optimization levels O0, O1, and O2;
- debug levels g0 and g2.

That produces exactly **2,304 serialized bytecodes** from 128 source programs: 768 cases for each bytecode generation. The generator checks the version byte of every emitted binary before adding it to the manifest.

Sources cover arithmetic, complex conditionals, while/repeat/numeric/generic loops, closures, recursion, multiple returns, varargs, tables, strings, methods, table-held functions, multiple assignments, and nested control flow. They intentionally avoid syntax unavailable in the oldest pinned compiler.

Generated sources and bytecodes are CI artifacts rather than committed binaries. The manifest records every compiler profile, bytecode version, optimization level, debug variant, source oracle, and tag.

## Metrics

The benchmark records these values per backend and case:

1. execution result, empty output, error, or timeout;
2. elapsed time and peak process-tree RSS when the operating system exposes it;
3. output length and SHA-256;
4. Luau syntax validity;
5. successful bytecode recompilation;
6. deterministic stdout equivalence against the original source;
7. explicit low-level fallback count;
8. generated-identifier ratio, structural similarity, formatting score, and combined readability;
9. aggregate stability, median time, p95 time, median memory, and maximum memory.

LunaUX itself runs through a subprocess adapter, so its timeout and memory boundary matches the external competitors.

## Release gate

The 0.18 Medal gate passes only when all of the following are true:

- LunaUX is not worse than Medal in recompilation rate;
- LunaUX is not worse in semantic equivalence;
- LunaUX is not worse in median readability;
- LunaUX is not worse in stability;
- LunaUX strictly improves at least one of those metrics;
- LunaUX wins more paired cases than it loses;
- LunaUX records no timeout.

A paired case is ranked first by actual execution status, then by semantic equivalence, recompilation, syntax, fallback count, and readability. A crash, error, timeout, or empty artifact cannot defeat a successful decompilation merely because later validators were skipped.

The release runner refuses an incomplete corpus. It requires exactly balanced v3/v6/v11 coverage, all optimization levels, both debug modes, semantic source oracles, and the pinned Medal and Unluau adapters.

## Reproduce locally

```bash
python scripts/install_benchmark_tools.py --include-unluau
python scripts/generate_benchmark_corpus.py \
  --luau-v3-compile .benchmark-tools/bin/luau-v3-compile \
  --luau-v6-compile .benchmark-tools/bin/luau-v6-compile \
  --luau-v11-compile .benchmark-tools/bin/luau-v11-compile \
  --output benchmark-corpus-v018
python scripts/run_release_benchmark.py \
  benchmark-corpus-v018/manifest.json \
  --external-backends .benchmark-tools/backends.json \
  --toolchain .benchmark-tools/toolchain.json \
  --artifacts benchmark-results-v018/artifacts \
  --raw-report benchmark-results-v018/raw.json \
  --quality-report benchmark-results-v018/quality.json \
  --markdown-report benchmark-results-v018/README.md \
  --contender lunaux \
  --reference medal \
  --minimum-cases 2304 \
  --require-gate
```

The command exits nonzero when the corpus is incomplete or the Medal gate fails. GitHub Actions runs the same sequence and uploads the raw artifacts, JSON report, Markdown scoreboard, generated manifest, compiler map, backend configuration, and exact toolchain evidence even on failure.

## Scope and honesty

Closed services without a stable, authorized, reproducible command or API are not assigned invented scores. They can be added when an adapter can run the same public corpus. A 0.18 victory means the pinned report passed; it does not imply that LunaUX will beat every future version of every decompiler.
