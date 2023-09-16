#!/bin/bash

# Create a unique timestamped folder in /tmp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TEMP_DIR="/tmp/firmware_$TIMESTAMP"
mkdir $TEMP_DIR

# Step 1: Download and unzip firmware files to the unique timestamped folder
wget -P $TEMP_DIR https://github.com/renxida/zmk-config/releases/download/latest/lily58_left-nice_nano_v2-zmk.uf2
wget -P $TEMP_DIR https://github.com/renxida/zmk-config/releases/download/latest/lily58_right-nice_nano_v2-zmk.uf2

# Step 2: Ensure NICENANO exists before proceeding with the copy
while [ ! -d "/media/$USER/NICENANO" ]; do
    echo "Please plug in and reset the left half of the keyboard."
    sleep 1
done

# Copy the *left-nice_nano*.uf2 file
cp $TEMP_DIR/*left-nice_nano*.uf2 "/media/$USER/NICENANO/"

# Step 3: Wait for /media/$USER/NICENANO to disappear
while [ -d "/media/$USER/NICENANO" ]; do
    sleep 1
done

# Prompt the user to plug in and reset the right half of the keyboard

# Step 4: Wait for /media/$USER/NICENANO to reappear
while [ ! -d "/media/$USER/NICENANO" ]; do
    echo "Please plug in and reset the right half of the keyboard."
    sleep 1
done

# Step 5: Copy the *right-nice_nano*.uf2 file
cp $TEMP_DIR/*right-nice_nano*.uf2 "/media/$USER/NICENANO/"

# Step 6: Cleanup
rm -rf $TEMP_DIR

echo "Script executed successfully."
