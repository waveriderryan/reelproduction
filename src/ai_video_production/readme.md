# **Modules for AI Video Production**

---

## **1.Video Processing**
- [ ] Frame sampling
- [ ] Canvas cropping
- [ ] Resolution adjusting
- [ ] Clip concatenation

---

## **2.Video Analysis**
- [ ] Summarization
- [ ] Tagging
- [x] Events extraction

### Usage ###
Input:
- video file name with path
- Google GenAI API key
- Activity type ('high five', 'tennis match'...)

Entry point:
```shell
src\ai_video_production\video_analysis\extract_events.py
```
---

## **3.Video Production**
- [ ] Command generation
  - Select(clip_id, event_id)
  - Multi-select
  - Replay(clip_id, event_id)
  - ...
- [ ] Command execution

---

# Data Model
### Event
### Command

---
# Library
- Prompt library - event type, task...
- Command library