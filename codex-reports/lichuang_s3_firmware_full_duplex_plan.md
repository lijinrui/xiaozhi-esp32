# Lichuang ESP32-S3 固件全双工打断改造计划

生成时间：2026-06-03

## 0. 可检测 Goal

目标不是重新适配一块板，而是在现有 `lichuang-dev` 板级适配基础上，验证并补齐桌面机器人级播放中可打断体验：

```text
server TTS 播放中
设备端仍保持 mic capture / VAD / AEC
用户插话或唤醒词触发
设备立即发送 abort
设备立即停止 speaker playback 并清空播放队列
设备进入下一轮 listening/realtime 状态
```

第一阶段通过标准：

```text
1. 固件使用 BOARD_TYPE_LICHUANG_DEV_S3 构建和烧录。
2. 普通小智对话可用。
3. 播放中收到 server {"type":"tts","state":"stop"} 后，设备 200ms 内停止出声。
4. 播放中用户插话/唤醒能触发 AbortSpeaking() 并向 server 发送 abort。
5. abort 后 audio_decode_queue_ / audio_playback_queue_ 没有明显残留音频。
6. AEC 开启时默认进入 kListeningModeRealtime。
7. 播放中插话后能进入第二轮对话。
```

暂不作为第一阶段完成条件：

```text
商用级远场 AEC
复杂声学结构优化
重新设计协议
DeskEmoji 分支适配
```

## 1. 当前仓库现状

当前 `xiaozhi-esp32` 已经有立创实战派 ESP32-S3 板级适配：

```text
main/boards/lichuang-dev/
main/boards/lichuang-dev/config.h
main/boards/lichuang-dev/lichuang_dev_board.cc
main/boards/lichuang-dev/config.json
```

Kconfig/CMake 里已有：

```text
BOARD_TYPE_LICHUANG_DEV_S3
BOARD_TYPE "lichuang-dev"
```

现有硬件能力：

```text
ES8311 output
ES7210 input
ST7789 display
FT5x06/FT6336 touch
camera
BOOT button
```

音频/AEC 相关配置已经存在：

```text
AUDIO_INPUT_REFERENCE true
CONFIG_USE_DEVICE_AEC=y
Application 默认 AEC mode = kAecOnDeviceSide
kAecOnDeviceSide -> kListeningModeRealtime
```

结论：

```text
不要从 DeskEmoji 分支继续做。
不要重新从零做立创板适配。
后续工作是围绕 lichuang-dev 做真机验证、播放队列清理、播放中监听和 AEC 调试。
```

## 2. 分支策略

当前立创全双工固件任务已从固件 `main` 单独开分支：

```text
feat/lichuang-s3-full-duplex
```

DeskEmoji 分支是独立任务：

```text
feat/deskemoji-board
```

要求：

```text
1. 不在 feat/deskemoji-board 上继续做立创改造。
2. 不直接在固件 main 上做全双工实验。
3. server 暂不合 main，真机联调时使用 server 的 feat/server-offline-barge-in-turns 分支或对应测试部署。
4. 本地构建产物 build-lichuang/ 和 sdkconfig.bak 不提交。
```

## 3. 阶段 A：基础真机复测

目标：

```text
确认现有 lichuang-dev 固件仍能正常构建、烧录、连接 server、完成普通对话。
```

任务：

```text
1. 选择 BOARD_TYPE_LICHUANG_DEV_S3。
2. 构建并烧录。
3. 配网并连接已通过第一阶段验收的 server。
4. 做 5 轮普通对话。
5. 记录启动日志中的 audio codec、input_reference、AEC mode、listening mode。
```

验收：

```text
普通对话能完成。
设备能播放 TTS。
设备能采音并上传。
没有明显 crash/reboot/audio init error。
```

## 4. 阶段 B：server stop 到设备停播验证

现有 server 已能在 abort 后快速下发：

```json
{"type":"tts","state":"stop"}
```

固件现有逻辑在 `application.cc` 收到 `tts stop` 后会从 speaking 切换状态，但要确认是否真正清掉音频播放残留。

任务：

```text
1. 在播放长 TTS 时，让 server 或测试脚本发送 tts stop。
2. 测量设备从收到 tts stop 到 speaker 实际静音的时间。
3. 检查 audio_decode_queue_ / audio_playback_queue_ 是否仍有残留。
4. 检查 decoder 是否需要 ResetDecoder()。
```

可能修改点：

```text
Application::OnIncomingJson tts stop 分支
AudioService::ResetDecoder()
AudioService::Stop()
audio_decode_queue_
audio_playback_queue_
```

建议实现：

```text
收到 tts stop 且当前 state == speaking:
  audio_service_.ResetDecoder()
  清 audio_decode_queue_ / audio_playback_queue_
  停止当前播放残留
  按 listening_mode_ 切 Listening 或 Idle
```

验收：

```text
tts stop 后 <= 200ms 停止出声。
不会继续播放上一轮残留音频。
下一轮 TTS 能正常起播。
```

## 5. 阶段 C：播放中设备端 abort

现有固件已经有：

```text
Application::AbortSpeaking()
Protocol::SendAbortSpeaking()
HandleWakeWordDetectedEvent() 中 speaking/listening 状态可触发 abort
```

但需要真机确认“播放中用户插话”是否真的触发。

任务：

```text
1. 设备正在 speaking 时，说唤醒词或按键触发打断。
2. 确认固件调用 AbortSpeaking()。
3. 确认 websocket 发出 {"type":"abort"}。
4. 确认 server 回 tts stop。
5. 确认设备进入 listening/realtime。
```

可能修改点：

```text
HandleWakeWordDetectedEvent()
AbortSpeaking()
SetListeningMode()
GetDefaultListeningMode()
```

验收：

```text
播放中插话 -> server 收到 abort <= 500ms。
server 下发 stop 后设备无残留播放。
第二轮 listen/start 或 realtime audio 能继续。
```

## 6. 阶段 D：确认播放中 mic capture/realtime mode

现有逻辑：

```text
kAecOnDeviceSide -> kListeningModeRealtime
Speaking 状态下只有 AFE wake word 可以检测
```

任务：

```text
1. 确认默认 AEC mode 是 kAecOnDeviceSide。
2. 确认默认 listening mode 是 kListeningModeRealtime。
3. 播放中检查 AudioProcessor 是否仍在运行。
4. 播放中检查 VAD/wake word 是否有事件。
5. 若播放中没有 mic 数据，定位 EnableVoiceProcessing(true/false) 状态切换。
```

可能修改点：

```text
Application::SetDeviceState(kDeviceStateSpeaking)
Application::SetDeviceState(kDeviceStateListening)
AudioService::EnableVoiceProcessing()
AfeAudioProcessor::Start()/Stop()
```

验收：

```text
speaking 时 mic capture 没有完全停掉。
唤醒词或 VAD 可在播放中触发打断。
```

## 7. 阶段 E：AEC/reference 通道验证

现有 `lichuang-dev` 使用 `BoxAudioCodec`：

```text
input_reference_ = true
input_channels_ = input_reference_ ? 2 : 1
ES7210 selected MIC1 | MIC2 | MIC3 | MIC4
AFE input_format 根据 input_channels/reference 自动生成 M/R
```

这里需要重点验证：

```text
ES7210 实际采集的通道顺序
MIC1/MIC2 是否是用户语音
MIC3 是否是 ES8311 playback feedback
当前 input_channels_ = 2 是否足够，还是需要 3/4 通道输入格式
AFE input_format 是否正确表达 M/M/R 或 M/M/N/R
```

任务：

```text
1. 增加音频诊断模式，录原始 ES7210 PCM。
2. 播放固定测试音，同时录输入通道。
3. 分离各通道保存为 wav。
4. 在电脑上看波形/听声音，确认 reference 通道。
5. 如果当前只读 2 通道但板子实际需要 3 通道，修改 BoxAudioCodec input_channels_/channel_mask/input_format。
```

建议诊断产物：

```text
mic_ch0.wav
mic_ch1.wav
ref_ch2.wav
raw_interleaved.wav
serial log: channel rms/peak/clipping
```

验收：

```text
播放时 reference 通道有稳定播放信号。
不播放时 reference 通道接近安静。
人说话主要进入 mic 通道，而不是 reference 通道。
没有明显 clipping。
```

## 8. 阶段 F：AEC 模式调试

现有 `AfeAudioProcessor`：

```text
afe_config_init(input_format, NULL, AFE_TYPE_VC, AFE_MODE_HIGH_PERF)
afe_config->aec_mode = AEC_MODE_VOIP_HIGH_PERF
CONFIG_USE_DEVICE_AEC 时 aec_init = true, vad_init = false
```

第一版建议：

```text
1. 先让 AEC output 服务于 barge-in 判断。
2. 暂时不要急着把 AEC output 作为最终 ASR 输入。
3. 调低喇叭音量，避免物理回声过强。
4. 调 input_gain_，避免 MIC/reference clipping。
```

可测试组合：

```text
AEC off + auto stop
AEC on device side + realtime
不同 output_volume
不同 input_gain
不同播放音量/距离
```

验收：

```text
只播放不说话：VAD/wake false trigger 明显减少。
播放时说话：能触发 abort。
不播放时说话：ASR 正常。
AEC on 比 AEC off 的播放中误触发/漏检更好。
```

## 9. 建议改动清单

优先级 P0：

```text
1. 基于 lichuang-dev 新建干净分支。
2. 增加/确认 tts stop 后 ResetDecoder + 清播放队列。
3. 增加日志：收到 tts stop、AbortSpeaking、listening mode、AEC mode、queue size。
4. 真机跑播放中 abort 验证。
```

优先级 P1：

```text
1. 增加音频诊断模式，能 dump ES7210 原始通道。
2. 确认 reference 通道顺序和增益。
3. 根据诊断结果修 BoxAudioCodec 的 input_channels_/channel_mask/input_format。
4. 调 AEC mode/input_gain/output_volume。
```

优先级 P2：

```text
1. 增加屏幕上的 AEC/Listening/Realtime 状态显示。
2. 增加按键或 MCP 工具切换 AEC mode。
3. 长时间稳定性测试。
```

## 10. 不建议现在做

```text
不要继续改 DeskEmoji 分支。
不要重写整个 AudioService。
不要一开始就追商用级 AEC。
不要在没有通道诊断前盲调 AEC 参数。
不要把 server 协议再大改一轮。
```

## 11. 推荐下一步

```text
1. 使用 server feat/server-offline-barge-in-turns 分支或对应测试 server 做真机联调；server 暂不合 main。
2. 在 xiaozhi-esp32 的 feat/lichuang-s3-full-duplex 分支继续固件改造。
3. 用现有 lichuang-dev 固件跑真机 smoke。
4. 如果 stop 有残留，先修 ResetDecoder/clear queue。
5. 如果播放中不能触发 abort，修 speaking 状态下的 voice processing/wake/VAD。
6. 如果 AEC 效果不稳定，再做三路音频诊断和 input_format 修正。
```

## 12. 本地离线验证结果（2026-06-03）

已完成不依赖模型、不依赖真机的本地验证：

```text
ESP-IDF: /Users/wangjinyuan1/esp/esp-idf
idf.py --version: ESP-IDF v5.5.2
branch: feat/lichuang-s3-full-duplex
```

构建命令：

```bash
source /Users/wangjinyuan1/esp/esp-idf/export.sh >/tmp/xiaozhi-idf-export.log
idf.py -B build-lichuang \
  -DSDKCONFIG=/private/tmp/xiaozhi-lichuang-sdkconfig \
  -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.esp32s3;/private/tmp/xiaozhi-lichuang.defaults" \
  build
```

临时 defaults：

```text
CONFIG_BOARD_TYPE_LICHUANG_DEV_S3=y
CONFIG_USE_DEVICE_AEC=y
```

构建结论：

```text
PASS
target: esp32s3
board: CONFIG_BOARD_TYPE_LICHUANG_DEV_S3=y
device AEC: CONFIG_USE_DEVICE_AEC=y
server AEC: # CONFIG_USE_SERVER_AEC is not set
xiaozhi.bin size: 0x2cc2e0
smallest app partition: 0x3f0000
free: 0x123d20, about 29%
```

生成的主要产物：

```text
build-lichuang/bootloader/bootloader.bin
build-lichuang/partition_table/partition-table.bin
build-lichuang/ota_data_initial.bin
build-lichuang/xiaozhi.bin
build-lichuang/generated_assets.bin
```

静态代码复核结论：

```text
1. CONFIG_USE_DEVICE_AEC 会让 Application 默认 aec_mode_ = kAecOnDeviceSide。
2. kAecOnDeviceSide 下 GetDefaultListeningMode() 返回 kListeningModeRealtime。
3. AbortSpeaking() 会调用 protocol_->SendAbortSpeaking(reason)。
4. HandleWakeWordDetectedEvent() 在 speaking/listening 状态可触发 AbortSpeaking(kAbortReasonWakeWordDetected)。
5. AudioService::ResetDecoder() 会清 timestamp_queue_、audio_decode_queue_、audio_playback_queue_、audio_testing_queue_。
6. 收到 server tts stop 的分支目前主要切状态，没有直接调用 audio_service_.ResetDecoder()。
```

因此，离线验证后的第一优先级代码任务仍然是：

```text
收到 {"type":"tts","state":"stop"} 且设备正在 speaking 时，
立即 ResetDecoder()/清播放队列，
并通过日志或测试确认不会继续播放上一轮残留音频。
```

本地验证无法覆盖的部分：

```text
1. speaker 实际停播延迟。
2. 播放中 mic capture 是否持续。
3. ES7210 实际通道顺序和 reference 通道。
4. AEC 对播放回声、误唤醒、漏打断的真实效果。
5. 插话后第二轮对话的整链路体验。
```

## 13. P0 代码改动与验证（2026-06-03）

已实际改动：

```text
main/application.cc
```

改动内容：

```text
收到 {"type":"tts","state":"stop"} 且当前状态是 kDeviceStateSpeaking 时：
1. 打日志：TTS stopped, clearing decoder and playback queues
2. 立即调用 audio_service_.ResetDecoder()
3. 再按 listening_mode_ 切到 Idle 或 Listening
```

新增离线验证脚本：

```text
scripts/verify_firmware_barge_in.py
```

脚本检查的关键约束：

```text
1. tts stop 分支必须存在。
2. tts stop 分支必须在 speaking 状态下处理。
3. tts stop 分支必须调用 audio_service_.ResetDecoder()。
4. ResetDecoder() 必须发生在 SetDeviceState() 之前。
5. AudioService::ResetDecoder() 必须清 timestamp_queue_、audio_decode_queue_、audio_playback_queue_、audio_testing_queue_。
6. ResetDecoder() 必须 notify audio_queue_cv_。
7. AbortSpeaking() 必须向 server 发送 abort。
8. AEC 开启时默认 listening mode 必须是 kListeningModeRealtime。
```

已跑验证：

```bash
python3 scripts/verify_firmware_barge_in.py
```

结果：

```text
PASS: firmware barge-in source invariants hold
```

已跑立创板构建：

```bash
source /Users/wangjinyuan1/esp/esp-idf/export.sh >/tmp/xiaozhi-idf-export.log
idf.py -B build-lichuang \
  -DSDKCONFIG=/private/tmp/xiaozhi-lichuang-sdkconfig \
  -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.esp32s3;/private/tmp/xiaozhi-lichuang.defaults" \
  build
```

结果：

```text
PASS
xiaozhi.bin binary size: 0x2cc340
smallest app partition: 0x3f0000
free: 0x123cc0, about 29%
```

这次代码改动解决的是 server 已经验证过的 abort/stop 链路中的固件侧第一缺口：

```text
server 下发 tts stop 后，设备不应继续播放旧 decoder/playback queue 中的残留音频。
```

仍需真机验证：

```text
1. stop 到实际 speaker 静音是否 <= 200ms。
2. 播放中唤醒词/插话是否稳定触发 AbortSpeaking()。
3. AEC/reference 通道是否正确。
```

## 14. 本地 abort 立即停播改动（2026-06-03）

继续补齐第二个稳妥改动：

```text
main/application.cc
```

改动内容：

```text
AbortSpeaking(reason) 中：
1. 记录 abort reason 和当前 state。
2. 仍然先向 server 发送 abort，保持 server 侧取消低延迟。
3. 如果当前 state == kDeviceStateSpeaking，立即 audio_service_.ResetDecoder()。
```

原因：

```text
播放中用户本地插话/唤醒已经触发 AbortSpeaking() 时，
设备端不应该等 server 回 {"type":"tts","state":"stop"} 才清旧 TTS 队列。
```

边界：

```text
1. 只在当前状态是 kDeviceStateSpeaking 时清播放队列。
2. listening/idle 等状态调用 AbortSpeaking() 不会额外 ResetDecoder()。
3. 后续 server tts stop 再 ResetDecoder() 一次是幂等行为。
```
