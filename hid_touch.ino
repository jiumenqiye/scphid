/*
 * ESP32-S3 HID Touchscreen (Android/Windows compatible)
 * -----------------------------------------------------------------
 * - This version initializes the HID device as a pointer (nullptr)
 * and creates the instance dynamically within the initDevice() function.
 * - Supports dynamic resolution changes via Serial command.
 * - HID descriptor declares a single touch contact report.
 * - Serial protocol for touch reports (binary):
 * - Header: 0xF4
 * - Report: 11 bytes matching the HID descriptor structure.
 * - Serial protocol for resolution change (binary):
 * - Header: 0xF4
 * - Command byte: 0x03
 * - New Max X: 4 bytes, little-endian (uint32_t)
 * - New Max Y: 4 bytes, little-endian (uint32_t)
 */
#include "USB.h"
#include "USBHID.h"
#include <string.h>
// #include <Preferences.h> // 用于访问非易失性存储
// Using macros instead of "magic numbers" improves readability and maintainability.
// These values are byte offsets calculated from the report_descriptor below.
#define REPORT_DESC_MAX_X_OFFSET 41
#define REPORT_DESC_MAX_Y_OFFSET 56

// Preferences preferences;
USBHID HID;

// HID Report Descriptor
// Defines a touchscreen device with information for one touch point (status, ID, X/Y coordinates)
// and the total number of contacts.
static uint8_t report_descriptor[] = {
    0x05, 0x0D, // Usage Page (Digitizer)
    0x09, 0x04, // Usage (Touch Screen)
    0xA1, 0x01, // Collection (Application)
    // Finger 1
    0x09, 0x22, //   Usage (Finger)
    0xA1, 0x02, //   Collection (Logical)
    0x09, 0x42, //     Usage (Tip Switch)
    0x15, 0x00, //     Logical Minimum (0)
    0x25, 0x10, //     Logical Maximum (1)
    0x75, 0x01, //     Report Size (1)
    0x95, 0x01, //     Report Count (1)
    0x81, 0x02, //     Input (Data,Var,Abs)
    0x95, 0x07, //     Report Count (7) - padding to full byte
    0x81, 0x03, //     Input (Const,Var,Abs)
    0x09, 0x51, //     Usage (Contact Identifier)
    0x75, 0x08, //     Report Size (8)
    0x95, 0x01, //     Report Count (1)
    0x81, 0x02, //     Input (Data,Var,Abs)
    0x05, 0x01, //     Usage Page (Generic Desktop)
    // X
    0x09, 0x30,                             // Usage (X)
    0x15, 0x00,                             // Logical Minimum (0)
    0x27, /*41 ->*/ 0xfe, 0xff, 0xff, 0x7f, // Logical Maximum (1440 << 8)
    0x75, 0x20,                             // Report Size (32)
    0x95, 0x01,                             // Report Count (1)
    0x81, 0x02,                             // Input (Data,Var,Abs)
    // Y
    0x09, 0x31,                             // Usage (Y)
    0x15, 0x00,                             // Logical Minimum (0)
    0x27, /*56 ->*/ 0xfe, 0xff, 0xff, 0x7f, // Logical Maximum (3200 << 8)
    0x75, 0x20,                             // Report Size (32)
    0x95, 0x01,
    0x81, 0x02,
    0xC0, //   End Collection
    // Contact Count
    0x05, 0x0D, // Usage Page (Digitizer)
    0x09, 0x54, // Usage (Contact Count)
    0x25, 0x02, // Logical Maximum (2)
    0x75, 0x08, // Report Size (8)
    0x95, 0x01, // Report Count (1)
    0x81, 0x02, // Input (Data,Var,Abs)
    0xC0        // End Collection (Application)
};
class CustomHIDDevice : public USBHIDDevice
{
public:
    CustomHIDDevice(void)
    {
        static bool initialized = false;
        if (!initialized)
        {
            initialized = true;
            HID.addDevice(this, sizeof(report_descriptor));
        }
    }

    uint16_t _onGetDescriptor(uint8_t *buffer)
    {
        memcpy(buffer, report_descriptor, sizeof(report_descriptor));
        return sizeof(report_descriptor);
    }

    void begin(void)
    {
        HID.begin();
    }

    bool send(uint8_t *value, uint16_t len)
    {
        return HID.SendReport(0, value, len);
    }
};

CustomHIDDevice *Device = nullptr;

#define MAGIC_HEADER 0xF4
#define CMD_OTHER 0x03
#define SERIAL_BUFFER_SIZE 11

void initDevice()
{
    if (Device)
    {
        delete Device;
    }
    Device = new CustomHIDDevice();
    Device->begin();
    USB.begin();
    unsigned long start = millis();
    while (!HID.ready() && (millis() - start < 3000))
    {
        delay(10);
    }
    if (HID.ready())
    {
        Serial.println("INFO: HID ready.");
    }
    else
    {
        Serial.println("ERROR: HID initialization failed.");
        delete Device;
        Device = nullptr;
    }
    delay(1000); // Wait for serial monitor to connect
    Serial.println("INFO: HID Touch init over");
}

void setup()
{
    Serial.setRxBufferSize(2048); // Increase serial receive buffer size
    Serial.begin(2000000);
    Serial.println("\n\nINFO: Device initialization");
    initDevice(); // Now, initialize the device with the new descriptor
}

static uint8_t serial_buffer[SERIAL_BUFFER_SIZE];
void loop()
{
   
    if (Serial.available() > 0 && Serial.read() == MAGIC_HEADER)
    {
        while (Serial.available() < SERIAL_BUFFER_SIZE)
        {
        }
        Serial.readBytes(serial_buffer, SERIAL_BUFFER_SIZE);
        // Serial.printf("BYTES : %d %d %d %d %d %d %d %d %d %d %d\n", serial_buffer[0], serial_buffer[1], serial_buffer[2], serial_buffer[3], serial_buffer[4], serial_buffer[5], serial_buffer[6], serial_buffer[7], serial_buffer[8], serial_buffer[9], serial_buffer[10]);
        if (serial_buffer[0] == CMD_OTHER)
        {
           //pass
        }
        else
        {
            if (Device)
            {
                Device->send(serial_buffer, SERIAL_BUFFER_SIZE);
            }
        }
    }
}
