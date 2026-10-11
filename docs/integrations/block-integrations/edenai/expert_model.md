# Edenai Expert Model
<!-- MANUAL: file_description -->
A generic block that calls any Eden AI expert model (OCR and document parsing, image and text analysis, web, audio, video) through the V3 Universal AI endpoint, for features without a dedicated block. Requires an Eden AI API key (`edenai` credential) from https://app.edenai.run.
<!-- END MANUAL -->

## Eden AI Expert Model

### What it is
Calls any Eden AI expert model (OCR, document parsing, image analysis, text analysis, web, audio, ...) through the Universal AI endpoint.

### How it works
<!-- MANUAL: how_it_works -->
The block posts `{model, input}` to the Universal AI endpoint and returns Eden AI's normalized `output`, the provider that served the request and its USD cost. `input` holds the feature-specific fields listed by `GET https://api.edenai.run/v3/info/<feature>/<subfeature>`; files are passed as a public URL or an Eden AI file ID, and some providers require a `language` code. Models whose subfeature ends in `_async` (multipage OCR, table extraction, video) are run as jobs and polled until done. Optional `provider_params` are forwarded to the provider and `fallbacks` lists providers to try if the primary one fails.
<!-- END MANUAL -->

### Inputs

| Input | Description | Type | Required |
|-------|-------------|------|----------|
| model | Eden AI expert model, `feature/subfeature/provider[/model]`, e.g. 'text/named_entity_recognition/amazon', 'ocr/financial_parser/google' or 'image/object_detection/amazon'. Async models (subfeature ending in '_async') are polled until done. The catalog is at https://api.edenai.run/v3/info. | str | Yes |
| input | Feature specific input, e.g. {'text': '...', 'language': 'en'} or {'file': '<URL or Eden AI file ID>'}. Some providers require a language code. | Dict[str, Any] | Yes |
| provider_params | Provider-specific parameters forwarded as-is. | Dict[str, Any] | No |
| fallbacks | Up to 3 fallback providers tried in order if the primary one fails. | List[str] | No |

### Outputs

| Output | Description | Type |
|--------|-------------|------|
| error | Error message if the operation failed | str |
| output | Normalized output of the expert model | Output |
| provider | Provider that served the request | str |
| cost | Cost of the request in USD | float |

### Possible use case
<!-- MANUAL: use_case -->
**Document parsing**: Extract structured fields from invoices with `ocr/financial_parser/<provider>` or from resumes with `ocr/resume_parser/<provider>`.

**Image and text analysis**: Detect objects with `image/object_detection/<provider>` or entities with `text/named_entity_recognition/<provider>` without a dedicated block.
<!-- END MANUAL -->

---
