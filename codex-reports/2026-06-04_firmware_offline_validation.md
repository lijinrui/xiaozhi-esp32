# 2026-06-04 固件侧全双工离线验证记录

分支：`feat/lichuang-s3-full-duplex`

目标：验证不依赖真机声学环境即可确认的固件侧全双工/打断基础能力。

## 1. 已验证项目

### 1.1 源码不变量验证

命令：

```bash
python3 scripts/verify_firmware_barge_in.py
```

结果：

```text
PASS: firmware barge-in source invariants hold
```

覆盖项：

```text
1. 收到 server {"type":"tts","state":"stop"} 时，只在 Speaking 状态清播放队列。
2. tts stop 在离开 Speaking 前调用 audio_service_.ResetDecoder()。
3. ResetDecoder() 清理 timestamp_queue_、audio_decode_queue_、audio_playback_queue_、audio_testing_queue_。
4. ResetDecoder() notify audio_queue_cv_，避免等待者卡住。
5. AbortSpeaking() 会发送 protocol_->SendAbortSpeaking(reason)。
6. AbortSpeaking() 只在当前状态是 Speaking 时本地 ResetDecoder()。
7. tts start 会记录可选 turn_id。
8. tts stop 在双方都有 turn_id 且不匹配时会忽略 stale stop。
9. 缺失或非字符串 turn_id 会落为空字符串，兼容旧 server。
10. AEC 开启时默认 listening mode 是 kListeningModeRealtime。
11. Speaking 状态在 realtime listening mode 下不会关闭 voice processing。
12. 立创板 `AUDIO_INPUT_REFERENCE true`。
13. 立创板 config.json 包含 `CONFIG_USE_DEVICE_AEC=y`。
```

### 1.2 立创 ESP32-S3 + device AEC 构建验证

命令：

```bash
source /Users/wangjinyuan1/esp/esp-idf/export.sh >/tmp/xiaozhi-idf-export.log
printf 'CONFIG_BOARD_TYPE_LICHUANG_DEV_S3=y\nCONFIG_USE_DEVICE_AEC=y\n' > /private/tmp/xiaozhi-lichuang.defaults
idf.py -B build-lichuang \
  -DSDKCONFIG=/private/tmp/xiaozhi-lichuang-sdkconfig \
  -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.esp32s3;/private/tmp/xiaozhi-lichuang.defaults" \
  build
```

结果：

```text
Project build complete.
xiaozhi.bin binary size 0x2cc6c0 bytes.
Smallest app partition is 0x3f0000 bytes.
0x123940 bytes (29%) free.
```

说明：

```text
1. 构建目标为 esp32s3。
2. ESP-IDF 版本为 5.5.2。
3. 立创板 + CONFIG_USE_DEVICE_AEC=y 构建通过。
4. 构建中出现 linux/ioctl.h 与 lwip sockets 的 _IO/_IOR/_IOW redefine warning，属于既有第三方头文件告警，本次未发现由全双工改动引起的编译错误。
```

## 2. 离线无法证明的项目

以下必须真机验证：

```text
1. ES7210 实际 mic/reference 通道顺序是否正确。
2. AEC reference 信号是否真实接入且有效。
3. 播放 TTS 时，用户普通音量插话是否能被稳定采集/识别。
4. 设备是否会把自身 TTS 误识别成用户语音。
5. 收到 tts stop 或本地 AbortSpeaking 后，speaker 实际静音时间是否 <= 200ms。
6. 桌面摆放、音量、外壳结构对回声和串音的影响。
```

## 3. 当前结论

```text
固件侧可离线验证的关键逻辑均通过。

从离线角度看，当前固件已经具备：
  server stop 清旧播放队列
  本地 abort 清旧播放队列
  turn_id stop guard
  立创板 device AEC/reference 配置
  AEC 模式下默认 realtime listening

下一步不建议继续盲改固件主逻辑。
应进入真机验证：
  播放中插话上行
  AEC/reference 有效性
  stop/abort 到实际静音延迟
```

## 4. 临时产物

本次构建生成：

```text
build-lichuang/
/private/tmp/xiaozhi-lichuang.defaults
/private/tmp/xiaozhi-lichuang-sdkconfig
```

`build-lichuang/` 是未跟踪构建目录，可删除；如果需要直接烧录，也可保留其中的 `xiaozhi.bin`、`generated_assets.bin` 和 `flash_args`。

