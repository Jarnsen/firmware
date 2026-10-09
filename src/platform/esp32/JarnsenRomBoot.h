#ifndef JARNSEN_ROM_BOOT_H
#define JARNSEN_ROM_BOOT_H

#if defined(CONFIG_IDF_TARGET_ESP32S3)
#include "esp_system.h"
#include "soc/rtc_cntl_reg.h"

namespace JarnsenRomBoot
{
inline void enterEsp32S3DownloadMode()
{
    REG_WRITE(RTC_CNTL_OPTION1_REG, RTC_CNTL_FORCE_DOWNLOAD_BOOT);
    esp_restart();
}
} // namespace JarnsenRomBoot
#endif

#endif // JARNSEN_ROM_BOOT_H
