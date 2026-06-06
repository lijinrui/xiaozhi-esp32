#include <esp_log.h>
#include <esp_err.h>
#include <esp_system.h>
#include <esp_heap_caps.h>
#include <esp_psram.h>
#include <nvs.h>
#include <nvs_flash.h>
#include <driver/gpio.h>
#include <esp_event.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include "application.h"

#define TAG "main"

static const char* ResetReasonToString(esp_reset_reason_t reason)
{
    switch (reason) {
        case ESP_RST_POWERON:
            return "POWERON";
        case ESP_RST_EXT:
            return "EXT";
        case ESP_RST_SW:
            return "SW";
        case ESP_RST_PANIC:
            return "PANIC";
        case ESP_RST_INT_WDT:
            return "INT_WDT";
        case ESP_RST_TASK_WDT:
            return "TASK_WDT";
        case ESP_RST_WDT:
            return "WDT";
        case ESP_RST_DEEPSLEEP:
            return "DEEPSLEEP";
        case ESP_RST_BROWNOUT:
            return "BROWNOUT";
        case ESP_RST_SDIO:
            return "SDIO";
        default:
            return "UNKNOWN";
    }
}

static void LogBootDiagnostics()
{
    auto reset_reason = esp_reset_reason();
    ESP_LOGW(TAG, "Boot reset reason: %s (%d)", ResetReasonToString(reset_reason), reset_reason);
    ESP_LOGI(TAG, "Heap: free=%u min_free=%u internal_free=%u internal_min_free=%u",
        heap_caps_get_free_size(MALLOC_CAP_DEFAULT),
        heap_caps_get_minimum_free_size(MALLOC_CAP_DEFAULT),
        heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
        heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL));
    if (esp_psram_is_initialized()) {
        ESP_LOGI(TAG, "PSRAM: size=%u free=%u min_free=%u",
            esp_psram_get_size(),
            heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
            heap_caps_get_minimum_free_size(MALLOC_CAP_SPIRAM));
    } else {
        ESP_LOGW(TAG, "PSRAM is not initialized");
    }
}

extern "C" void app_main(void)
{
    LogBootDiagnostics();

    // Initialize NVS flash for WiFi configuration
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "Erasing NVS flash to fix corruption");
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    // Initialize and run the application
    auto& app = Application::GetInstance();
    app.Initialize();
    app.Run();  // This function runs the main event loop and never returns
}
