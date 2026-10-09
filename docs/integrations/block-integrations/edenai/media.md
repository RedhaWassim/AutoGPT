# Edenai Media
<!-- MANUAL: file_description -->
_Add a description of this category of blocks._
<!-- END MANUAL -->

## Eden AI Generate Image

### What it is
Generates an image from a text prompt with an Eden AI expert model.

### How it works
<!-- MANUAL: how_it_works -->
_Add technical explanation here._
<!-- END MANUAL -->

### Inputs

| Input | Description | Type | Required |
|-------|-------------|------|----------|
| prompt | Text description of the image to generate | str | Yes |
| model | Eden AI image generation model, `image/generation/<provider>[/<model>]` (bytedance, google, leonardo, minimax, openai, stabilityai, ...). | str | No |
| resolution | Image size such as '1024x1024'. The provider default is used when empty. | str | No |
| fallbacks | Up to 3 fallback providers tried in order if the primary one fails. | List[str] | No |

### Outputs

| Output | Description | Type |
|--------|-------------|------|
| error | Error message if the operation failed | str |
| image | The generated image | str (file) |

### Possible use case
<!-- MANUAL: use_case -->
_Add practical use case examples here._
<!-- END MANUAL -->

---

## Eden AI Speech To Text

### What it is
Transcribes speech from an audio or video file with an Eden AI expert model.

### How it works
<!-- MANUAL: how_it_works -->
_Add technical explanation here._
<!-- END MANUAL -->

### Inputs

| Input | Description | Type | Required |
|-------|-------------|------|----------|
| audio | Audio or video file to transcribe: a URL, a workspace file or a data URI. | str (file) | Yes |
| model | Eden AI speech-to-text model, `audio/speech_to_text_async/<provider>[/<model>]` (amazon, assembly, deepgram, gladia, google, ...). | str | No |
| language | Language code of the speech, e.g. 'en'. Detected by most providers when empty. | str | No |
| fallbacks | Up to 3 fallback providers tried in order if the primary one fails. | List[str] | No |

### Outputs

| Output | Description | Type |
|--------|-------------|------|
| error | Error message if the operation failed | str |
| text | The transcription | str |
| speakers | Speaker segments, when the provider returns diarization | List[Dict[str, Any]] |

### Possible use case
<!-- MANUAL: use_case -->
_Add practical use case examples here._
<!-- END MANUAL -->

---

## Eden AI Text To Speech

### What it is
Converts text to speech with an Eden AI expert model.

### How it works
<!-- MANUAL: how_it_works -->
_Add technical explanation here._
<!-- END MANUAL -->

### Inputs

| Input | Description | Type | Required |
|-------|-------------|------|----------|
| text | Text to convert to speech | str | Yes |
| model | Eden AI text-to-speech model, `audio/tts/<provider>[/<model>]` (amazon, deepgram, elevenlabs, google, microsoft, openai, ...). | str | No |
| voice | Provider voice name or ID. The provider default is used when empty. | str | No |
| audio_format | Audio format, e.g. 'mp3' or 'wav'. The provider default is used when empty. | str | No |

### Outputs

| Output | Description | Type |
|--------|-------------|------|
| error | Error message if the operation failed | str |
| audio | The generated speech | str (file) |

### Possible use case
<!-- MANUAL: use_case -->
_Add practical use case examples here._
<!-- END MANUAL -->

---
