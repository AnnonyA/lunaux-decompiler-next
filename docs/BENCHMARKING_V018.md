# LunaUX 0.18 differential benchmark

LunaUX 0.18 replaces feature-count claims with a public, reproducible comparison. The same serialized Luau bytecode is sent to LunaUX, Medal, Unluau, and any additional command backend using one manifest and one scoring contract.

## Pinned inputs

`benchmarks/pins.json` fixes every tool to an exact Git commit:

- Luau supplies the compiler, parser, recompiler, and semantic runtime;
- Medal is the primary 0.18 reference;
- Unluau is the secondary public reference.

Medal also requires unstable Rust features and did not publish a dependency lock at the pinned commit. The repository therefore records Rust 1.87.0, enables the feature gate with `RUSTC_BOOTSTRAP=1`, and stores the exact resolved `Cargo.lock` as `benchmarks/medal-Cargo.lock.gz.b64`. The installer verifies its decompressed SHA-256 before invoking Cargo with `--locked`. This preserves Medal's source commit and edition without applying source patches while eliminating registry drift.

`python scripts/install_benchmark_tools.py --include-unluau` verifies each checkout before building it and writes generated `toolchain.json` and `backends.json` files. No backend is invoked through a shell.

## Public corpus

`python scripts/generate_benchmark_corpus.py` creates source and bytecode deterministically. The release matrix contains:

- 16 semantic program families;
- 24 deterministic seeds per family;
- optimization levels O0, O1, and O2;
- debug levels g0 and g2.

That produces exactly **2,304 serialized bytecodes** from 384 source programs. Sources cover arithmetic, complex conditionals, while/repeat/numeric/generic loops, closures, recursion, multiple returns, varargs, tables, strings, methods, table-held functions, multiple assignments, and nested control flow.

Generated sources and bytecodes are CI artifacts rather than committed binaries. The manifest records every case, optimization level, debug variant, source oracle, and tag.

## Metrics

The benchmark records these values per backend and case:

1. execution result, crash, error, or timeout;
2. elapsed time and peak process-tree RSS when the operating system exposes it;
3. output length and SHA-256;
4. Luau syntax validity;
5. successful bytecode recompilation;
6. deterministic stdout equivalence against the original source;
7. explicit low-level fallback count;
8. generated-identifier ratio, structural similarity, formatting score, and combined readability;
9. aggregate stability, median time, p95 time, median memory, and maximum memory.

LunaUX itself runs through a subprocess adapter, so its timeout and memory boundary is the same as the external competitors.

## Release gate

The 0.18 Medal gate passes only when all of the following are true:

- LunaUX is not worse than Medal in recompilation rate;
- LunaUX is not worse in semantic equivalence;
- LunaUX is not worse in median readability;
- LunaUX is not worse in stability;
- LunaUX strictly improves at least one of those metrics;
- LunaUX wins more paired cases than it loses;
- LunaUX records no timeout.

A case is ranked by semantic equivalence, recompilation, syntax, fallback count, and readability, in that order. Empty output, crashes, validator errors, and timeouts cannot be hidden by a good-looking artifact.

## Reproduce locally

```bash
python scripts/install_benchmark_tools.py --include-unluau
python scripts/generate_benchmark_corpus.py \
  --luau-compile .benchmark-tools/bin/luau-compile \
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

The command exits nonzero when the corpus is incomplete or the Medal gate fails. GitHub Actions runs the same sequence and uploads the raw artifacts, JSON report, Markdown scoreboard, generated manifest, and exact tool configurations even on failure.

## Scope and honesty

Closed services without a stable, authorized, reproducible command or API are not assigned invented scores. They can be added when an adapter can run the same public corpus. A 0.18 victory means the pinned report passed; it does not imply that LunaUX will beat every future version of every decompiler.
