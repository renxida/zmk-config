cmake_minimum_required(VERSION 3.20.0)

# Pull in the usb-bootloader-touch module (two levels up).
get_filename_component(MODULE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
set(ZEPHYR_EXTRA_MODULES ${MODULE_ROOT})

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(usb_bl_touch_test)

target_sources(app PRIVATE src/main.c)
