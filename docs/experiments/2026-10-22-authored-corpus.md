# Authored SSE corpus evaluation, 2026-10-22

Environment: local Windows, Python 3.15; dependency-free runtime. Commands: `py -m unittest discover -s tests -v` with `PYTHONPATH=src`, and `py -m streamreceipt benchmark --out artifacts` with `PYTHONPATH=src`.

| Checker | Correct verdicts / 13 | Method |
|---|---:|---|
| Parse-only baseline | 4 | Concatenate tool JSON fragments and accept any JSON object. Ignores terminal and usage evidence. |
| StreamReceipt 0.1 | 13 | Provider-specific terminal, stop, lifecycle, metadata, argument and optional usage checks. |

The first implementation scored 12/13; the Anthropic open-block case exposed an incorrectly inconclusive verdict. A blocking-code correction brought the repeat to 13/13. Ten unit tests passed after the correction and an additional cumulative-usage test. Raw case verdicts are in `artifacts/benchmark.json`, and the generated visual is `artifacts/benchmark.svg`.

Interpretation: the baseline is deliberately weak and the corpus was authored with the implementation. This supports a reproducible regression claim on these cases only. It does not measure independent stream compatibility, false positives, provider billing accuracy, latency or real-world adoption.

Packaging and independent checks: Ruff 0.17.2 lint and format checks passed. Setuptools 84.2.1 built a source archive and universal wheel. A separate Python 3.15 virtual environment installed the wheel with `--no-deps --no-index`, passed all 10 tests, and reproduced 13/13 versus 4/13. Both example SSE transcripts returned `dispatch_allowed` with usage observed. Generated SVG parsed as XML and was visually inspected in a local browser. One README had zero em-dash characters, and a targeted credential-pattern scan found no matches. `pip check` found no broken requirements.
