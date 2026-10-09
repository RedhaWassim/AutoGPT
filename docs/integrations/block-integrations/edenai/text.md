# Edenai Text
<!-- MANUAL: file_description -->
_Add a description of this category of blocks._
<!-- END MANUAL -->

## Eden AI Extract Text

### What it is
Extracts the text of an image or PDF (OCR) with an Eden AI expert model.

### How it works
<!-- MANUAL: how_it_works -->
_Add technical explanation here._
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
_Add practical use case examples here._
<!-- END MANUAL -->

---

## Eden AI Moderate Text

### What it is
Checks text for offensive, sexual, violent, hateful or self-harm content with an Eden AI expert model.

### How it works
<!-- MANUAL: how_it_works -->
_Add technical explanation here._
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
_Add practical use case examples here._
<!-- END MANUAL -->

---

## Eden AI Translate Text

### What it is
Translates text into another language with an Eden AI expert model.

### How it works
<!-- MANUAL: how_it_works -->
_Add technical explanation here._
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
_Add practical use case examples here._
<!-- END MANUAL -->

---
