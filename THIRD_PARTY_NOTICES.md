# Third-Party Notices

AQA's own source code is licensed under the MIT License in `LICENSE`. Third-party components retain their own licenses. The source repository keeps full license texts and component-level inventories in `THIRD_PARTY_LICENSES/`. Desktop packages install AQA's license as `AQA-LICENSE.txt` and third-party material in the adjacent `third-party/` directory; the package paths below refer to that layout.

## Components Included In Desktop Packages

- **Embedded Python runtime** — CPython 3.13.14 from the `python-build-standalone` 20260623 release. Its CPython and native-library license texts are in `third-party/python-build-standalone-20260623/`.
- **Python packages** — exact versions are listed in `third-party/RUNTIME_DEPENDENCIES.txt`. The package copies retain available `*.dist-info/licenses/` files inside the embedded runtime, including the Requests NOTICE and pip's vendored-component licenses. Loguru 0.7.3 omits its license file from the installed metadata, so its exact upstream MIT text is supplied separately as `third-party/LOGURU-0.7.3-MIT.txt`.
- **Frontend JavaScript** — exact production-lock entries, source links, copyright notices, and full license texts are in `third-party/FRONTEND_DEPENDENCIES.txt`.
- **Rust desktop shell** — exact target-filtered crates, source links, and full license texts are in `third-party/RUST_DEPENDENCIES.html`. This includes the MPL-2.0 components `cssparser`, `dtoa-short`, `option-ext`, and `selectors`. Corresponding source is available from the exact crate links in that file; the MPL-2.0 text is also in `third-party/MPL-2.0.txt`. Rust standard-library copyright and dual MIT/Apache-2.0 texts from the build toolchain are in the adjacent `RUST_STDLIB_*` files. `third-party/RUST_TOOLCHAIN.json` records the exact compiler source revision and hashes of the generated inputs and outputs; packaging fails if the active toolchain or those files no longer match.

## Bundled Assets

### OpenAI o200k_base Encoding Data

- Package path: `data/tokenizers/o200k_base.tiktoken`
- Source: <https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken>
- Size: 3,613,922 bytes
- SHA-256: `446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d`
- Upstream reference: OpenAI `tiktoken` commit [`9d01e5670ff50eb74cdb96406c7f3d9add0ae2f8`](https://github.com/openai/tiktoken/blob/9d01e5670ff50eb74cdb96406c7f3d9add0ae2f8/tiktoken_ext/openai_public.py#L91-L95) identifies this exact URL and digest.
- License: MIT; full text: `third-party/TIKTOKEN-MIT.txt`
- Modifications: none; the committed file was byte-identical to the upstream object checked on 2026-09-17.

The data file has no embedded license marker and is hosted outside the source repository. In response to that exact ambiguity for externally hosted encoding files, an official `tiktoken` collaborator stated that the repository license applies to the encoding files and closed [`openai/tiktoken#92`](https://github.com/openai/tiktoken/issues/92#issuecomment-1497875652). Together with the later official `o200k_base` URL/hash registration, this establishes the available redistribution basis under the repository's MIT license. The clarification is an issue comment from 2023 rather than durable asset-level metadata and predates `o200k_base`; moving it into upstream license documentation would improve provenance durability but is not treated here as a remaining permission blocker.

### Tomorrow Fonts

- Files: `Tomorrow-SemiBold.ttf`, `Tomorrow-Black.ttf`
- Copyright: Copyright 2019 The Tomorrow Project Authors
- License: SIL Open Font License 1.1
- Source: <https://github.com/google/fonts/tree/main/ofl/tomorrow>
- SHA-256: `27f99342d00d33da5a5c89cf53e58a09a6e079d07511edbac9594713bd2368b6` and `50f588a001797ba6db023d00c1950cb33c983786d9e809c6e1473669ec2b167e`
- Full text: `third-party/TOMORROW-OFL-1.1.txt`

### Material Symbols Rounded Subsets

- Files: `MaterialSymbolsRounded-AQA.ttf` and `MaterialSymbolsRounded-AQA-Filled.ttf`
- Copyright recorded in the fonts: Copyright Google LLC
- License: Apache License 2.0
- Source project: <https://github.com/google/material-design-icons>
- SHA-256: `b4905f4da16eef3b5b4ec246ad8a1e1c4222635ecb270929f510c190969e47d3` and `d632b769751065068ca963719978677b830441b43f0ba8e00a10059b2e7a8854`
- Full text: `third-party/APACHE-2.0.txt`

These are Material Symbols, not the distinct classic Material Icons set. The font files were obtained through the Google Fonts CSS API for Material Symbols Rounded at optical size 24, weight 400, grade 0, and fill 0 or 1. AQA's `scripts/trim_gsub_ligatures.py` removes unused GSUB ligature substitutions and stores the outputs under AQA-specific filenames; the internal upstream family names and copyright metadata are retained. The mutable Google Fonts input URL, input binary hash, and fontTools version used for the committed files were not recorded, so their historical input revision is not recoverable and an exact byte-for-byte rebuild is not yet deterministic.

### Material Symbols Droplet Artwork

The AQA logo, animated brand, favicon, and generated desktop icons are modified derivatives of the Material Symbols `humidity_low`, `humidity_mid`, and `humidity_high` 24px designs—not the classic Material Icons `water_drop` icon. Their geometry matches the Rounded sources at [`google/material-design-icons` revision `6d7ca43`](https://github.com/google/material-design-icons/tree/6d7ca43bd6e6668531a00fcaca06d921b63dd716/symbols/web), the earliest identified repository revision with the exact AQA 960-grid paths; older related 24-grid versions do not contain those exact paths. AQA converted path commands without changing geometry, then scaled, colored, composed, and animated the symbols; the favicon adds a custom background, and Tauri converts it to PNG/ICO/ICNS application icons. The exact original acquisition/export revision was not preserved, so the cited revision is a verified geometry match, not a claim about the historical download event. The designs and modifications are covered by Apache-2.0; the full text is `third-party/APACHE-2.0.txt`. No upstream `NOTICE` file exists at the cited revision.

## Components Downloaded After Installation

These are not inside the desktop installer, but AQA can download them to its per-user Local AI directory:

- **llama.cpp `b10976` runtime archives** — MIT; exact archive URLs, sizes, and SHA-256 values are fixed in the application catalog. Full text: `third-party/LLAMA_CPP-MIT.txt`. AQA also preserves the upstream `LICENSE` member when macOS and Linux archives are installed; Windows release archives do not contain that file, so the bundled application copy remains the notice.
- **Gemma 4 E2B, E4B, and 12B QAT GGUF model and MTP files** — downloads pinned to immutable repository commits from the exact Unsloth repositories [`E2B`](https://huggingface.co/unsloth/gemma-4-E2B-it-qat-GGUF/tree/66a399f68ddd113b06dff02fca9523e55465d11d) at `66a399f68ddd113b06dff02fca9523e55465d11d`, [`E4B`](https://huggingface.co/unsloth/gemma-4-E4B-it-qat-GGUF/tree/8c5a9e4fd5482e2be20fe0bf013b4c262a8f4265) at `8c5a9e4fd5482e2be20fe0bf013b4c262a8f4265`, and [`12B`](https://huggingface.co/unsloth/gemma-4-12B-it-qat-GGUF/tree/980b060c40a8539ac159e0501a3e0f66a6365af3) at `980b060c40a8539ac159e0501a3e0f66a6365af3`. Each exact repository card identifies Apache-2.0, links Google's [Gemma 4 license](https://ai.google.dev/gemma/docs/gemma_4_license), and lists the target and MTP filenames used by AQA. Full text: `third-party/APACHE-2.0.txt`. AQA verifies each file's exact byte count and SHA-256 before installation. The source repository's `docs/INTEGRATED_AI_MODEL_PROVENANCE.md` lists filenames, byte counts, and expected payload digests; that document is not included in desktop packages. Repository Git revisions identify commits; Git LFS SHA-256 identities identify GGUF payload bytes. LFS pointer Git object IDs and delivery-layer HTTP ETags are distinct metadata and are not substituted for payload digests.
- **NVIDIA CUDA Runtime and cuBLAS companions** — optional NVIDIA profiles download hash-pinned llama.cpp `b10976` companion archives after AQA is installed. They are not present in AQA desktop installers. AQA extracts only the named CUDA Runtime, cuBLAS, and cuBLASLt object-code libraries beside `llama-server`; it does not modify their bytes.

  | AQA profile              | Exact NVIDIA components established from the `b10976` build and NVIDIA redistributable manifests        | Companion SHA-256                                                  | Applicable terms supplied with AQA            |
  | ------------------------ | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ | --------------------------------------------- |
  | Windows x86-64 CUDA 12.4 | `cuda_cudart` 12.4.127; `libcublas` 12.4.5.8; `cublas64_12.dll`, `cublasLt64_12.dll`, `cudart64_12.dll` | `8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6` | `third-party/NVIDIA-CUDA-EULA-2024-01-12.txt` |
  | Linux x86-64 CUDA 12.8   | `cuda_cudart` 12.8.90; `libcublas` 12.8.5.5; `libcudart.so.12`, `libcublas.so.12`, `libcublasLt.so.12`  | `08e11f701ad2957021af68c9f2b81f0c4ea2e616fffc4c3e482c30b61dc90044` | `third-party/NVIDIA-CUDA-EULA-2024-01-12.txt` |
  | Linux ARM64 CUDA 13.3    | `cuda_cudart` 13.3.29; `libcublas` 13.6.0.2; `libcudart.so.13`, `libcublas.so.13`, `libcublasLt.so.13`  | `e8cc4f80afeff5043dbf9a42430278f27230bd9a31e3ef5de0082dd217e842d3` | `third-party/NVIDIA-CUDA-EULA-2026-01-26.txt` |
  | Windows ARM64 CUDA 13.4  | `cuda_cudart` 13.4.49; `libcublas` 13.7.0.27; `cublas64_13.dll`, `cublasLt64_13.dll`, `cudart64_13.dll` | `642dcde8805b3e3165ca710a5443b3b4044b27d96bd3ee3132473988c9bcb774` | `third-party/NVIDIA-CUDA-EULA-2026-01-26.txt` |

  NVIDIA's exact-version redistributable manifests label both `cuda_cudart` and `libcublas` as governed by the CUDA Toolkit license and point to the LICENSE file included in each official component archive. The 12.4 and 12.8 archives carry byte-identical January 12, 2024 terms; the 13.3 and 13.4 archives carry semantically identical January 26, 2026 terms (the Windows copy differs only by line endings). Because the llama.cpp companion repacks contain only the three libraries, AQA verifies the matching bundled text and copies it unchanged beside the libraries during installation and repair.

  NVIDIA components are licensed by NVIDIA under the supplied CUDA EULAs, including their application-integration, application-only-access, downstream-terms, notice-retention, NVIDIA-GPU-only, and redistribution conditions. They are not covered by AQA's MIT license. Including the matched texts preserves the applicable notices; it does not constitute NVIDIA approval or a claim that all legal requirements are satisfied.

The Windows desktop installer also embeds Microsoft's Evergreen WebView2 Standalone Installer under Tauri's `offlineInstaller` mode. Microsoft documents that offline distribution path; the Microsoft installer retains its own terms. Linux WebKitGTK and macOS WebKit are platform dependencies rather than files copied by AQA's staging script.

## Source And Scope

The component inventories named above record exact versions, source links, copyright notices, and license texts. Packaging verifies the required notice and license files against the source copies in `THIRD_PARTY_LICENSES/`. Build/test dependencies are excluded unless their code or generated content is included in a distributable. Listing a component here does not relicense it or claim comprehensive legal clearance.
