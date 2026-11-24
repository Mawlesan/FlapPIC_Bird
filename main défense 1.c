#include "sysconfig.h"
#include <xc.h>
#include <stdint.h>
#include <string.h>

#include "usb.h"
#include "usb_device.h"
#include "usb_device_cdc.h"   

#define _XTAL_FREQ 48000000UL   // pour __delay_ms

static uint8_t usbReadBuffer[64];
static uint8_t usbWriteBuffer[64];

static void initUSBLib(void){
    USBDeviceInit();
    USBDeviceAttach();
}

static uint8_t isUSBReady(void){
    return (USBGetDeviceState() == CONFIGURED_STATE) && (USBIsDeviceSuspended() == false);
}

static void initIO(void){
    // Tout en numérique (évite surprises sur certains ports)
    ADCON1 = 0x0F;

    // RB0 en entrée (bouton)
    TRISBbits.TRISB0 = 1;

    // Active les pull-ups PortB (si jumpers en Pull-Up, ça marche ; sinon sans effet)
    INTCON2bits.RBPU = 0;
}

void main(void)
{
    initIO();
    initUSBLib();

    static const char FLAP_MSG[]  = "FLAP\n";
    static const char READY_MSG[] = "READY\n";

    // Etat de référence au démarrage (pull-up -> 1 relâché ; pull-down -> 0 relâché)
    uint8_t released = PORTBbits.RB0;

    // Lissage
    uint8_t stable_state = released;   // état validé par le debounce
    uint8_t last_sample  = released;
    uint16_t stable_ms   = 0;

    // Latch: 1 = prêt à déclencher, 0 = on attend relâchement
    uint8_t armed = 1;

    uint16_t hb = 0; // heartbeat

    while(1)
    {
        USBDeviceTasks();
        if(!isUSBReady()) continue;

        (void)getsUSBUSART(usbReadBuffer, sizeof(usbReadBuffer));

        // Heartbeat ~2 s
        if(++hb >= 2000) {
            hb = 0;
            if(mUSBUSARTIsTxTrfReady()){
                putUSBUSART((uint8_t*)READY_MSG, (uint8_t)strlen(READY_MSG));
            }
        }

        // ---- Debounce 1 ms / lecture RB0 ----
        uint8_t s = PORTBbits.RB0;
        if(s == last_sample) {
            if(stable_ms < 1000) stable_ms++;   // cap pour éviter overflow
        } else {
            stable_ms = 0;
            last_sample = s;
        }
        if(stable_ms >= 30) {                   // 30 ms de stabilité
            stable_state = s;
        }

        // Press détecté = transition vers l'état "appuyé"
        uint8_t pressed_level = (released == 1) ? 0 : 1;  // gère pull-up OU pull-down
        if(armed && (stable_state == pressed_level)) {
            if(mUSBUSARTIsTxTrfReady()){
                putUSBUSART((uint8_t*)FLAP_MSG, (uint8_t)strlen(FLAP_MSG));
            }
            armed = 0; // ne plus déclencher tant que pas relâché
        }

        // Ré-armement quand relâché (stable)
        if(!armed && (stable_state == released)) {
            armed = 1;
        }

        CDCTxService();
        __delay_ms(1); // base de temps 1 ms
    }
}
