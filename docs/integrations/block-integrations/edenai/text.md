# Edenai Text
<!-- MANUAL: file_description -->
Text and document blocks backed by Eden AI expert models through the V3 Universal AI endpoint (`POST https://api.edenai.run/v3/universal-ai`): OCR, translation and moderation. Each block picks its provider with an Eden AI model string `feature/subfeature/provider[/model]`, so switching provider is a one-field change. Requires an Eden AI API key (`edenai` credential) from https://app.edenai.run.
<!-- END MANUAL -->

## Eden AI Extract Text

### What it is
Extracts the text of an image or PDF (OCR) with an Eden AI expert model.

### How it works
<!-- MANUAL: how_it_works -->
The block sends the file to the `ocr/ocr/<provider>` model and returns the extracted text. Public URLs are passed to Eden AI as-is; workspace files and data URIs are first uploaded to Eden AI file storage (`POST /v3/upload`) and referenced by file ID. Requests use `output_format=compact`, which drops per-word bounding boxes. Optional `fallbacks` lists providers Eden AI tries in order if the primary one fails. The USD cost Eden AI reports is recorded for billing; a failed provider call raises a block error.
<!-- END MANUAL -->

### Inputs

| Input | Description | Type | Required |
|-------|-------------|------|----------|
| file | Image or PDF to read: a URL, a workspace file or a data URI. | str (file) | Yes |
| model | Eden AI OCR model, `ocr/ocr/<provider>[/<model>]` (amazon, google, microsoft, mistral, ...). | str | No |
| language | Language code of the document, e.g. 'en'. Most providers detect it. | str | No |
| fallbacks | Up to 3 fallback providers tried in order if the primary one fails, e.g. ['google'] or ['ocr/ocr/google']. | List[str] | No |

### Outputs

| Output | Description | Type |
|--------|-------------|------|
| error | Error message if the operation failed | str |
| text | Text extracted from the document | str |

### Possible use case
<!-- MANUAL: use_case -->
**Invoice intake**: Read uploaded invoices or receipts to text, then pass the text to an AI Structured Response Generator block to extract amounts and dates.

**Scanned document search**: OCR scanned PDFs before chunking and embedding them for retrieval.
<!-- END MANUAL -->

---

## Eden AI Moderate Text

### What it is
Checks text for offensive, sexual, violent, hateful or self-harm content with an Eden AI expert model.

### How it works
<!-- MANUAL: how_it_works -->
The block sends the text to the `text/moderation/<provider>` model and returns an overall `nsfw_likelihood` from 1 (unlikely) to 5 (very likely) plus the detected categories (hate, harassment, sexual, violence, self-harm, ...) with their likelihood. Optional `fallbacks` lists providers to try if the primary one fails.
<!-- END MANUAL -->

### Inputs

| Input | Description | Type | Required |
|-------|-------------|------|----------|
| text | Text to moderate | str | Yes |
| model | Eden AI moderation model, `text/moderation/<provider>[/<model>]` (google, microsoft, openai, ...). | str | No |
| fallbacks | Up to 3 fallback providers tried in order if the primary one fails, e.g. ['google'] or ['ocr/ocr/google']. | List[str] | No |

### Outputs

| Output | Description | Type |
|--------|-------------|------|
| error | Error message if the operation failed | str |
| nsfw_likelihood | Overall likelihood the text is harmful, from 1 (unlikely) to 5 (very likely) | int |
| categories | Detected categories with their likelihood | List[Dict[str, Any]] |

### Possible use case
<!-- MANUAL: use_case -->
**User content gate**: Route user submissions with a high `nsfw_likelihood` to a review branch before publishing.

**Agent output check**: Moderate generated replies before they are posted to a community channel.
<!-- END MANUAL -->

---

## Eden AI Translate Text

### What it is
Translates text into another language with an Eden AI expert model.

### How it works
<!-- MANUAL: how_it_works -->
The block sends the text to the `translation/automatic_translation/<provider>` model with the target language and, when set, the source language (otherwise detected by the provider). It returns the translated text. Optional `fallbacks` lists providers to try if the primary one fails.
<!-- END MANUAL -->

### Inputs

| Input | Description | Type | Required |
|-------|-------------|------|----------|
| text | Text to translate | str | Yes |
| target_language | Target language code, e.g. 'fr' | str | Yes |
| source_language | Source language code, e.g. 'en'. Detected when empty. | str | No |
| model | Eden AI translation model, `translation/automatic_translation/<provider>[/<model>]` (amazon, deepl, google, microsoft, modernmt, openai, ...). | str | No |
| fallbacks | Up to 3 fallback providers tried in order if the primary one fails, e.g. ['google'] or ['ocr/ocr/google']. | List[str] | No |

### Outputs

| Output | Description | Type |
|--------|-------------|------|
| error | Error message if the operation failed | str |
| translated_text | The translated text | str |

### Possible use case
<!-- MANUAL: use_case -->
**Multilingual support**: Translate incoming customer messages to English for triage, then translate the reply back.

**Content localisation**: Produce French, German and Spanish versions of a product description with providers such as DeepL or Google.
<!-- END MANUAL -->

---
