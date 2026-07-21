#include "TestUtil.h"
#include "modules/TacticalMapMath.h"

#include <cstring>
#include <unity.h>

static void test_mgrs10_at_utm_zone_center()
{
    char mgrs[24];
    TEST_ASSERT_TRUE(TacticalMapMath::formatMgrs10(0, 30000000, mgrs, sizeof(mgrs)));
    TEST_ASSERT_EQUAL_STRING("31N EA 00000 00000", mgrs);
}

static void test_mgrs_rejects_polar_latitude()
{
    char mgrs[24];
    TEST_ASSERT_FALSE(TacticalMapMath::formatMgrs10(850000000, 0, mgrs, sizeof(mgrs)));
    TEST_ASSERT_EQUAL_STRING("", mgrs);
}

static void test_bearing_and_mil_cardinal_directions()
{
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, TacticalMapMath::bearingDegrees(0, 0, 10000000, 0));
    TEST_ASSERT_EQUAL_UINT16(0, TacticalMapMath::degreesToMil(0.0f));
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 90.0f, TacticalMapMath::bearingDegrees(0, 0, 0, 10000000));
    TEST_ASSERT_EQUAL_UINT16(1600, TacticalMapMath::degreesToMil(90.0f));
    TEST_ASSERT_EQUAL_UINT16(3200, TacticalMapMath::degreesToMil(180.0f));
    TEST_ASSERT_EQUAL_UINT16(4800, TacticalMapMath::degreesToMil(270.0f));
    TEST_ASSERT_EQUAL_UINT16(4800, TacticalMapMath::degreesToMil(-90.0f));
}

static void test_distance_formatting()
{
    char value[16];
    TEST_ASSERT_EQUAL_STRING("385 m", TacticalMapMath::formatDistance(385.0f, value, sizeof(value)));
    TEST_ASSERT_EQUAL_STRING("2.34 km", TacticalMapMath::formatDistance(2340.0f, value, sizeof(value)));
}

static void test_position_age_formatting()
{
    char value[16];
    TEST_ASSERT_EQUAL_STRING("18 s", TacticalMapMath::formatPositionAge(18, value, sizeof(value)));
    TEST_ASSERT_EQUAL_STRING("3 min", TacticalMapMath::formatPositionAge(180, value, sizeof(value)));
    TEST_ASSERT_EQUAL_STRING("2 h", TacticalMapMath::formatPositionAge(7200, value, sizeof(value)));
}

static void test_map_range_uses_readable_steps()
{
    TEST_ASSERT_EQUAL_FLOAT(50.0f, TacticalMapMath::mapRangeMeters(20.0f));
    TEST_ASSERT_EQUAL_FLOAT(500.0f, TacticalMapMath::mapRangeMeters(385.0f));
    TEST_ASSERT_EQUAL_FLOAT(2500.0f, TacticalMapMath::mapRangeMeters(2340.0f));
}

void setUp(void) {}

void tearDown(void) {}

extern "C" {
void setup()
{
    initializeTestEnvironment();
    UNITY_BEGIN();
    RUN_TEST(test_mgrs10_at_utm_zone_center);
    RUN_TEST(test_mgrs_rejects_polar_latitude);
    RUN_TEST(test_bearing_and_mil_cardinal_directions);
    RUN_TEST(test_distance_formatting);
    RUN_TEST(test_position_age_formatting);
    RUN_TEST(test_map_range_uses_readable_steps);
    exit(UNITY_END());
}

void loop() {}
}
