# 全双工语音/文字交互架构研究与落地建议

生成时间：2026-06-03

目标：围绕“小智 ESP32-S3 桌面机器人”，研究最新 realtime voice agent / 全双工语音交互架构，并给出当前 `xiaozhi-esp32-server` + `xiaozhi-esp32` 可落地的升级建议。

## 1. 结论摘要

补充说明：当前时间是 2026-06-03，本报告以 2026 年 voice agent 技术状态为准。2025 的资料只作为工程背景；模型和架构判断优先参考 2026 年公开资料。

当前方向不需要推倒重来。最务实的路线是：

```text
保留 cascaded streaming pipeline：
ESP32 AFE/AEC/VAD/wake
-> server streaming ASR
-> turn manager / cancellation / partial intent
-> streaming LLM
-> streaming TTS
-> ESP32 playback
```

不要现在直接押注纯 speech-to-speech 大模型作为主链路。行业和论文都显示：端到端 realtime S2S 是趋势，但对可控性、工具调用、成本、本地部署和稳定性来说，当前工程主流仍是可取消、可观测、可替换的 cascaded streaming pipeline。

当前最值得继续投入的不是“大换模型”，而是：

```text
1. turn_id 贯穿 server 文本控制、TTS、工具调用、metrics。
2. 设备端播放中监听和本地 abort 继续打磨。
3. ASR partial 只做低风险 intent/slot/interrupt 分类，不直接喂给 LLM 生成最终回复。
4. 建立 false interruption 处理，而不是任何 VAD 都打断。
5. 建立 spoken commit / assistant history truncate，避免被打断后对话上下文假装用户听完了整句话。
6. 真机 AEC/reference 通道诊断，确认播放中能听见用户。
7. 建立端到端 latency/stale/interrupt 观测面板。
```

## 1.1 2026 最新判断

2026 年的趋势可以概括为：

```text
前沿模型：
  speech-to-speech / realtime multimodal voice 继续快速进步。

工程主线：
  可控、可观测、可取消的 cascaded streaming pipeline 仍然是最务实的产品架构。

关键升级点：
  micro-turn
  semantic triggering
  adaptive interruption
  spoken-history truncation
  turn/cancel observability
```

2026 关键来源：

- OpenAI 2026-05-07 发布新的 API 音频模型，包括 GPT-Realtime-2、GPT-Realtime-Translate、GPT-Realtime-Whisper： https://openai.com/index/advancing-voice-intelligence-with-new-models-in-the-api/
- DuplexCascade 2026 提出 VAD-free cascaded ASR-LLM-TTS full-duplex pipeline 和 micro-turn optimization： https://arxiv.org/abs/2603.09180
- Enterprise Realtime Voice Agents 2026 的技术教程认为，生产级 realtime voice 的关键是 streaming/pipelining，而不是单个模型；文中测得 cascaded pipeline 可做到 P50 first-audio 约 947ms： https://arxiv.org/abs/2603.05413
- LTS-VoiceAgent 2026 强调 semantic triggering 和 incremental reasoning，目标是在用户说完前开始“想”，但仍保持最终提交可控： https://arxiv.org/abs/2601.19952
- UAF 2026 尝试把 VAD、turn detection、speaker recognition、ASR、QA 等 full-duplex audio front-end 任务统一建模，但这更偏研究前沿： https://arxiv.org/abs/2604.19221

对本项目的 2026 结论：

```text
1. 不要把“全双工”理解成必须马上切到单个 speech-to-speech 大模型。
2. 你的 server/firmware 当前路线和 2026 cascaded + micro-turn 方向一致。
3. 下一步应该做 micro-turn / semantic trigger / adaptive interrupt，而不是只换 ASR/TTS provider。
4. GPT-Realtime-2 值得作为云端体验上限 benchmark，但不是当前低成本主链路。
```

## 2. 研究来源要点

### 2.1 OpenAI Realtime / WebRTC

OpenAI 官方 voice agents 文档建议 realtime 语音优先用低延迟传输，浏览器场景偏 WebRTC，server 场景可用 WebSocket：

- https://platform.openai.com/docs/guides/voice-agents
- https://platform.openai.com/docs/guides/realtime/

OpenAI 2026 的低延迟 voice 文章强调，实时语音体验的核心不是单个模型，而是低 jitter、低 packet loss、低 RTT 的媒体链路；他们在 WebRTC 基础上重构 routing/relay/transceiver 来保证实时交互：

- https://openai.com/index/delivering-low-latency-voice-ai-at-scale/

对本项目的含义：

```text
ESP32 端继续 WebSocket/Opus 是务实的，因为固件和 server 已经跑通。
但 PC 离线验证、浏览器验证、未来 App 入口可以引入 WebRTC。
不要为了 ESP32 现在硬切 WebRTC；先把 turn/cancel/AEC/metrics 做扎实。
```

### 2.2 LiveKit Agents

LiveKit 的 turn docs 把语音 agent 的核心拆成：

```text
turn detection
VAD / STT endpointing / model-based turn detector
interruption mode
adaptive interruption
false interruption recovery
preemptive generation
```

来源：

- https://docs.livekit.io/agents/build/turns/
- https://docs.livekit.io/agents/logic/turns/tuning/
- https://livekit.com/blog/turn-detection-voice-agents-vad-endpointing-model-based-detection

关键启发：

```text
1. 打断不是简单 VAD=true。
2. 好的系统要区分真实插话和“嗯、好、对”等 backchannel。
3. 被打断后，要截断 assistant history，只保留用户实际听到的部分。
4. 可以 preemptive generation，但必须可取消、可回滚。
```

对本项目的含义：

```text
server 需要从“收到 abort 就 cancel”升级为“interrupt classifier + cancellation + false interruption recovery”。
```

### 2.3 Pipecat

Pipecat 把语音系统抽象成 frame pipeline，核心是各种 frame processor 和 interruption frame：

- https://docs.pipecat.ai/guides/learn/pipeline

对本项目的含义：

```text
xiaozhi-server 可以不引入 Pipecat，但应该借鉴 frame/event 化：
AudioFrame
ASRPartialFrame
ASRFinalFrame
IntentFrame
LLMTokenFrame
TTSTextFrame
TTSAudioFrame
InterruptFrame
TurnCommitFrame
```

这样 provider 可替换、测试可注入、cancel 可传播。

### 2.4 ASR endpointing / partial

Deepgram 文档明确区分 interim results、is_final、speech_final，endpointing 可用毫秒参数控制暂停多久算结束：

- https://developers.deepgram.com/docs/endpointing
- https://developers.deepgram.com/docs/understand-endpointing-interim-results

AssemblyAI streaming 文档也强调 end-of-turn detection 和 streaming transcript：

- https://www.assemblyai.com/docs/speech-to-text/streaming

对本项目的含义：

```text
ASR partial 可以用于：
1. 屏幕显示
2. interrupt classifier
3. intent/slot 预判
4. 预热工具/schema/context

但不要把每个 partial 都直接提交给 LLM 做最终回复。
```

## 3. 模型/组件选型建议

### 3.1 ASR

当前最务实推荐：

```text
第一优先级：本地 FunASR streaming / Paraformer streaming / SenseVoice
第二优先级：Qwen Cloud realtime ASR 或 Qwen3-ASR 本地可跑后再接
第三优先级：Whisper/faster-whisper 作为离线或非实时 fallback
```

依据：

- FunASR 官方支持 real-time streaming、SDK 和服务部署： https://www.funasr.com/en/
- FunASR online SDK 文档包含 streaming ASR、VAD、punctuation： https://github.com/modelscope/FunASR/blob/main/runtime/docs/SDK_tutorial_online.md
- Qwen Cloud realtime ASR 官方提供实时语音识别接口： https://docs.qwencloud.com/developer-guides/speech/asr-realtime
- Qwen3-ASR 有公开资料称支持实时流式、多语言和噪声鲁棒，但本地工程化成熟度需要单独验证： https://qwen-ai.com/qwen-asr/

建议：

```text
在 M3 Ultra 上先跑 FunASR streaming 作为主 ASR baseline。
同时保留 Qwen3-ASRLocal provider，但不要在没有稳定 streaming benchmark 前替换主链路。
```

### 3.2 LLM

当前建议：

```text
主链路：MiniMax / Kimi 中选择实际 TTFT 更低、更稳定的一个。
备用：LM Studio 本地模型做实验/隐私/断网 fallback。
高质量远程：GPT 用于复杂推理或对比，不作为低延迟主链路。
```

重点不是换 LLM，而是加：

```text
1. streaming token cancel
2. turn_id stale token discard
3. function/tool future cancel
4. prefill/context cache
5. partial intent 只触发预热，不提交最终 assistant message
```

### 3.3 TTS

当前务实分层：

```text
Smoke / 免费验证：EdgeTTS
低延迟商业：Cartesia / ElevenLabs / OpenAI TTS streaming
本地探索：Kokoro / Qwen3-TTS / CosyVoice 系列
```

来源：

- ElevenLabs WebSocket realtime TTS 支持 chunk schedule 和 latency 优化： https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/realtime-tts
- ElevenLabs 解释 chunk size 与自然度/低延迟的权衡： https://elevenlabs.io/docs/eleven-api/concepts/audio-streaming
- Cartesia WebSocket TTS 用 context 表示对话 turn，适合 voice agent： https://docs.cartesia.ai/api-reference/tts/websocket
- Qwen3-TTS 官方仓库称支持 streaming speech generation： https://github.com/QwenLM/Qwen3-TTS
- Qwen3-TTS 技术报告描述 real-time synthesis 架构： https://arxiv.org/abs/2601.15621
- Kokoro 是轻量本地 TTS，适合低成本实验，但中文质量要实测： https://getstream.io/video/docs/python-ai/integrations/kokoro/

建议：

```text
短期继续 EdgeTTS 做链路调试。
产品体验验证优先试 Cartesia/ElevenLabs streaming。
本地 M3 探索 Kokoro/Qwen3-TTS，但不要让本地 TTS 卡住 server 架构改造。
GPT-SoVITS 既然之前卡，就暂时不作为主线。
```

## 4. 当前架构的主要改进空间

### 4.1 TurnManager 从“测试逻辑”升级为“核心状态机”

现在 server 已经开始有 turn_id、cancel_current_turn、stale packet metrics。下一步应该把它变成明确模块：

```text
TurnManager:
  begin_turn(source, query, audio_segment_id)
  cancel_turn(turn_id, reason)
  is_current(turn_id)
  bind_sentence(sentence_id, turn_id)
  bind_tool_future(future, turn_id)
  bind_tts_context(context_id, turn_id)
  mark_spoken(audio_seq/text_offset)
  summarize_metrics(turn_id)
```

必须支持：

```text
1. LLM token late output 丢弃。
2. TTS text late output 丢弃。
3. TTS audio late output 丢弃。
4. tool result late output 丢弃。
5. server 发给设备的 tts start/sentence_start/stop 都带 turn_id。
6. 设备如果支持 turn_id，则校验 tts stop。
```

当前固件已补：

```text
1. tts stop 清 playback queue。
2. 本地 AbortSpeaking 清 playback queue。
3. tts stop turn_id guard。
```

还缺：

```text
二进制 audio packet 没有 turn_id，旧 audio packet 过滤仍依赖 server 不发送旧包。
```

### 4.2 InterruptClassifier，而不是 VAD 直接 abort

播放中检测到人声时，不应立刻无脑 abort。建议分层：

```text
Layer 0: 设备端 AFE/wake word/energy/VAD
Layer 1: server ASR partial
Layer 2: lightweight interrupt intent classifier
Layer 3: policy decision
```

策略：

```text
强打断：
  唤醒词
  “停一下/别说了/等一下/我打断一下”
  明显新问题

弱打断/不打断：
  “嗯”
  “好”
  “对”
  笑声/咳嗽/环境声

需要恢复：
  误打断后用户没有继续说话，agent 可继续上一句或重新摘要接上。
```

落地：

```text
server 增加 interrupt_decider.py：
  input: vad_event, asr_partial, playback_state, current_turn_id
  output: ignore | soft_interrupt | hard_interrupt | resume_previous
```

### 4.3 Partial ASR 只做预测，不提交最终语义

建议规则：

```text
ASR partial:
  用于 UI、intent/slot 预判、工具预热、interrupt 分类。

ASR final:
  用于正式进入 LLM turn。
```

可以预热什么：

```text
1. RAG 检索候选。
2. intent router。
3. tool schema / device status。
4. LLM session/context cache。
5. TTS provider connection/context。
6. 常见固定回复模板。
```

不要预热：

```text
1. 真正执行有副作用的工具。
2. 提交 assistant message。
3. 播放最终 TTS。
```

### 4.4 Spoken Commit / History Truncation

LiveKit 的 interruption 思路里，一个关键点是：agent 被打断后，对话历史里不应保留用户没有听到的完整回复。

当前建议：

```text
server 维护 assistant_spoken_commit：
  turn_id
  sentence_id
  text_sent_to_tts
  audio_seq_sent
  estimated_played_ms
  device_ack_played_ms（未来）
```

被打断后：

```text
history 中 assistant message 只保留已播放/大概率已听到的部分。
未播放文本不要进入 history。
```

短期可以用估算：

```text
已发送给设备的 audio duration - jitter buffer - safety margin
```

长期最好设备回报：

```json
{
  "type": "playback",
  "state": "progress",
  "turn_id": "...",
  "played_ms": 1230
}
```

### 4.5 TTS Chunker 独立出来

LLM token 不应原样一段段喂给 TTS。建议独立：

```text
TTSChunker:
  accumulate tokens
  cut by punctuation / semantic boundary / max chars / max wait ms
  normalize text
  assign sentence_id
  bind turn_id
```

建议参数：

```text
first_chunk:
  8-20 Chinese chars or 150-300ms max wait

middle_chunk:
  punctuation boundary preferred
  max 40-80 Chinese chars

cancel:
  any pending chunk not yet sent to TTS must be discarded immediately
```

这样比“LLM 一段段回，TTS 一段段播”更稳。

### 4.6 Transport：ESP32 先不切 WebRTC，PC 验证可加 WebRTC

WebRTC 对浏览器/手机/PC voice agent 是主流，因为它自带：

```text
AEC / NS / AGC
RTP / jitter buffer
Opus
NAT traversal
low-latency media path
```

但 ESP32 固件切 WebRTC 成本高。建议：

```text
ESP32:
  继续 WebSocket + Opus + JSON control。

PC offline validator:
  增加 WebRTC/LiveKit/Pipecat 入口，用于快速验证新 pipeline。

未来 App:
  WebRTC 优先。
```

### 4.7 AEC/硬件侧

Espressif ESP-SR AFE 官方包含 AEC、NS、VAD、WakeNet，并定义 `M/R/N` input format；AEC 支持最多双麦处理，reference 通道用于播放回声消除：

- https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/audio_front_end/README.html

对立创板的落地任务：

```text
1. 真机录 ES7210 raw interleaved PCM。
2. 播固定测试音，确认哪个通道是 mic，哪个是 playback reference。
3. 检查 input_format 是 M/R、MMR、MMNR 中哪一种。
4. 测 AEC on/off 下播放中 VAD 误触发率和插话召回率。
```

## 5. 建议路线图

### 阶段 1：稳定现有链路（已部分完成）

```text
目标：
  server abort path 稳定
  固件 stop/abort 清播放队列
  tts stop turn_id guard

已完成：
  server offline 10/10
  real provider smoke
  firmware tts stop ResetDecoder
  firmware local abort ResetDecoder
  firmware tts stop turn_id guard

下一步：
  真机验证 stop->silent <= 200ms
  真机验证 speaking 中 wake/interrupt
```

### 阶段 2：server pipeline 模块化

```text
1. TurnManager 独立模块。
2. CancellationToken 贯穿 ASR/LLM/TTS/tool。
3. TTSChunker 独立模块。
4. InterruptClassifier 独立模块。
5. MetricsCollector 独立模块。
```

可测目标：

```text
abort_to_stop_ms P95 <= 50ms server-side
stale_audio_packets = 0
old_turn_llm_tokens_sent = 0
old_turn_tts_chunks_sent = 0
turn_id coverage = 100% for text control messages
```

### 阶段 3：partial ASR 预热

```text
1. ASR partial -> intent/slot candidate。
2. partial 只预热，不提交。
3. final ASR 才 begin committed LLM turn。
4. 对确定性强的命令可 early commit。
```

例子：

```text
partial: “把客厅灯...”
预热：home_control schema, device status
final: “把客厅灯调暗一点”
提交：function call
```

### 阶段 4：false interruption 和 resume

```text
1. 播放中检测到短 backchannel 不打断。
2. 误打断后 700-1200ms 内没有 ASR final，可恢复上一段。
3. 真正插话则 cancel current turn。
```

### 阶段 5：PC/WebRTC 验证入口

```text
1. 用电脑麦克风/扬声器模拟硬件。
2. WebRTC 或 LiveKit/Pipecat 做快速实验。
3. 同一个 server pipeline 可接 ESP32 和 PC client。
```

## 6. 现在最务实的下一批代码任务

### 6.0 可检测目标（给后续执行者）

总目标：

```text
在不依赖真机、不依赖付费云模型的情况下，先把 server 做成可取消、可观测、可回滚的 full-duplex turn pipeline。

输入：
  wav/pcm/文本脚本模拟用户第一轮、播放中插话、第二轮。

输出：
  server 明确停止旧 turn，丢弃旧 turn 的 LLM/TTS/tool late output，
  新 turn 能独立开始并产生首段 TTS audio/control message。
```

必须可自动化验证的指标：

```text
1. hard interrupt 后，server 发出 tts stop 的 P95 <= 50ms。
2. hard interrupt 后，old_turn_llm_tokens_sent = 0。
3. hard interrupt 后，old_turn_tts_chunks_sent = 0。
4. hard interrupt 后，old_turn_audio_packets_sent = 0。
5. tts start / sentence_start / stop 控制消息 turn_id 覆盖率 = 100%。
6. 第二轮 turn_id 必须不同于第一轮。
7. weak backchannel（嗯/好/对/笑声短音）默认不 cancel。
8. false interruption 触发后，如果 700-1200ms 内没有 ASR final，允许 resume 或至少不污染 history。
9. 被打断的 assistant message 只能把 spoken_commit 部分写进 history。
10. 所有指标写入离线测试报告，至少 10 次连续 PASS。
```

建议新增/收敛的测试脚本：

```text
tests/test_turn_manager_cancel.py
tests/test_tts_chunker.py
tests/test_interrupt_classifier.py
tests/test_spoken_commit_history.py
scripts/offline_full_duplex_turn_test.py
```

建议把“完成”的定义写死：

```text
如果只是在 abort 时发 stop，不算完成。
如果没有验证 late LLM/TTS/tool output 被丢弃，不算完成。
如果 history 仍然记录用户没听到的完整 assistant 回复，不算完成。
如果 ASR partial 能直接触发最终 LLM 回复，不算完成。
```

优先级 P0：

```text
1. server 增加 TurnManager 模块，收敛现有 turn/cancel 逻辑。
2. server 增加 TTSChunker，避免 LLM token 直接驱动 TTS。
3. server 增加 InterruptClassifier 雏形：
   VAD/wake/asr_partial/playback_state -> hard/soft/ignore。
4. server 增加 spoken commit 估算：
   哪些 assistant 文本大概率已播放。
5. 固件真机测试脚本：
   serial log + server metrics + stop->silent 人工/录音测量。
```

优先级 P1：

```text
1. FunASR streaming 本地 provider baseline。
2. Qwen3-ASRLocal benchmark。
3. Cartesia/ElevenLabs/Qwen3-TTS/Kokoro TTS provider benchmark。
4. PC client/WebRTC validator。
5. AEC raw channel dump。
```

优先级 P2：

```text
1. assistant history truncation with device playback ack。
2. false interruption resume。
3. server dashboard。
4. multi-client/session scale。
```

## 7. 不建议现在做

```text
1. 不建议现在把 ESP32 固件切 WebRTC。
2. 不建议现在上纯 speech-to-speech 作为唯一主链路。
3. 不建议 ASR partial 直接喂 LLM 生成最终回复。
4. 不建议继续在 GPT-SoVITS 上耗太多时间。
5. 不建议在 AEC reference 通道没确认前盲调参数。
```

## 8. 最短落地路径

```text
1. 保持当前 server feature 分支 + firmware feat/lichuang-s3-full-duplex。
2. 真机跑：
   长 TTS -> 插话 -> abort -> stop -> 第二轮
3. 如果 stop->silent 合格，开始 server 侧 TurnManager/TTSChunker/InterruptClassifier。
4. 同时在 M3 Ultra 跑 FunASR streaming，形成本地 ASR baseline。
5. TTS 先 EdgeTTS smoke，产品体验再试 Cartesia/ElevenLabs 或 Qwen3-TTS/Kokoro。
```
