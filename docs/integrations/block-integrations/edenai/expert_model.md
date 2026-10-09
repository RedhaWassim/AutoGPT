# Edenai Expert Model
<!-- MANUAL: file_description -->
_Add a description of this category of blocks._
<!-- END MANUAL -->

## Eden AI Expert Model

### What it is
Calls any Eden AI expert model (OCR, document parsing, image analysis, text analysis, web, audio, ...) through the Universal AI endpoint.

### How it works
<!-- MANUAL: how_it_works -->
_Add technical explanation here._
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
_Add practical use case examples here._
<!-- END MANUAL -->

---
