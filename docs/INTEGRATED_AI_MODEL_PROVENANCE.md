# Integrated AI Model Provenance

Verified on 2026-09-17 against the official Hugging Face repository API. AQA
pins each configured main model and matching MTP draft to one immutable
repository commit and verifies the downloaded bytes before publication.

| Model | Repository revision | Asset | Bytes | Expected file SHA-256 |
| --- | --- | --- | ---: | --- |
| Gemma 4 E2B | `unsloth/gemma-4-E2B-it-qat-GGUF` at `66a399f68ddd113b06dff02fca9523e55465d11d` | `gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf` | 2,620,370,976 | `e531007218dfab990486a5de7676a6932d6ea8dea233d1f698d7c21cf8a16889` |
| Gemma 4 E2B | same revision | `mtp-gemma-4-E2B-it.gguf` | 59,235,648 | `586f2460b909008640981ec34060aa864e03c144fbabfb3173c4335087e4aae0` |
| Gemma 4 E4B | `unsloth/gemma-4-E4B-it-qat-GGUF` at `8c5a9e4fd5482e2be20fe0bf013b4c262a8f4265` | `gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf` | 4,215,695,776 | `df0fd4ee07072c607c29a0a1cb4f98918426cca12f45a2776bdd6ee6d09a4de3` |
| Gemma 4 E4B | same revision | `mtp-gemma-4-E4B-it.gguf` | 59,678,016 | `423074e537504b4f9ec5eafed5c639fac82c96631626efccacdd3c4039b20605` |
| Gemma 4 12B | `unsloth/gemma-4-12B-it-qat-GGUF` at `980b060c40a8539ac159e0501a3e0f66a6365af3` | `gemma-4-12B-it-qat-UD-Q4_K_XL.gguf` | 6,716,356,800 | `90fd44e29e0d7cffeb0fd00dc73cfdab9ed0b0e95306ecf7821ea634c940c370` |
| Gemma 4 12B | same revision | `mtp-gemma-4-12B-it.gguf` | 253,708,800 | `fcb35dea42c71333db904cee11baac525c9ef872818ee3753f6cb156f3c6f4f6` |

## Identity Interpretation

- The 40-hex revision is the repository Git commit ID. Main and draft URLs use
  `resolve/<revision>/<filename>`, never the mutable `resolve/main` reference.
- The expected file SHA-256 is the official sibling metadata's Git LFS
  `lfs.sha256` value (`oid sha256` in the pointer). For these LFS assets it is
  the SHA-256 identity of the actual GGUF payload.
- The sibling `blobId` is the Git object ID of the small LFS pointer stored in
  the repository. It is not the GGUF payload hash.
- An HTTP ETag is not used as the expected file digest. Hugging Face's linked
  response metadata agrees with the LFS identity, but delivery-layer CDN/Xet
  ETags can identify a different storage object.

The authoritative metadata sources are the official revision-scoped API
responses with `blobs=true` for
[E2B](https://huggingface.co/api/models/unsloth/gemma-4-E2B-it-qat-GGUF/revision/66a399f68ddd113b06dff02fca9523e55465d11d?blobs=true),
[E4B](https://huggingface.co/api/models/unsloth/gemma-4-E4B-it-qat-GGUF/revision/8c5a9e4fd5482e2be20fe0bf013b4c262a8f4265?blobs=true),
and [12B](https://huggingface.co/api/models/unsloth/gemma-4-12B-it-qat-GGUF/revision/980b060c40a8539ac159e0501a3e0f66a6365af3?blobs=true).
The Hugging Face API contract identifies `blob_id` as the Git OID and exposes
LFS `size` and `sha256` metadata in its
[RepoSibling documentation](https://huggingface.co/docs/huggingface_hub/package_reference/hf_api).

## Selection And Verification Boundary

The table describes the configured catalog in `src/local_ai/catalog.py`.
Each main model and matching MTP file uses the listed repository revision;
model choice, quantization, and inference settings are independent of these
file-identity checks.

The inventory above is metadata verification. The implementation verifies the
full downloaded byte count and SHA-256 locally before atomically publishing an
artifact, and its tests exercise that path with small synthetic files. The
metadata verification recorded above did not independently download and hash
the six multi-gigabyte upstream payloads.
