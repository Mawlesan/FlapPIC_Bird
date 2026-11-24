#include "sysconfig.h"
#include "usb.h"
#include "usb_device.h"
#include "usb_device_cdc.h"
#include "usb_cdc_lib.h"
#include <xc.h>
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>

#define _XTAL_FREQ 48000000UL  // Fréquence système
#define FLAP_THRESHOLD 7000    // Seuil max Ultrason
#define SENSOR_DEADZONE 50     // Seuil mini Ultrason
volatile unsigned int timeout;
volatile unsigned int duration;

void InitializeSystem(void) {
    USBDeviceInit();      // Initialise USB
    USBDeviceAttach();    // Attache périphérique USB

    __asm(
        // Configuration Bouton
        "MOVLW 0x0F\n"    // ADCON1 = 0x0F; (DÉFINIR RB0/AN12 EN NUMÉRIQUE)
        "MOVWF ADCON1\n"
        "BSF TRISB, 0\n"  //TRISBbits.TRISB0 = 1; // RB0 entrée
        "CLRF LATB\n" 
            
        // Configuration Ultrason
        "BCF TRISC, 0\n"  //TRISCbits.TRISC0 = 0; // TRIG sortie
        "BSF TRISC, 1\n"  //TRISCbits.TRISC1 = 1; // ECHO entrée
        // Configuration Timer1
        "BCF T1CON, 1\n"  // TMR1CS = 0 
        "BCF T1CON, 5\n"  // T1CKPS0 = 0
        "BCF T1CON, 4\n"  // T1CKPS1 = 0 : Prédiviseur 1:1
        "BCF T1CON, 3\n"  // T1OSCEN = 0 : Oscillateur Timer1 désactivé
        "BCF T1CON, 0\n"  // TMR1ON = 0 : Timer1 OFF
    );


}

uint16_t MeasureEcho(void) {
    timeout = 30000;

    // --- Envoi impulsion TRIG (10 µs) ---
    __asm(
        "BSF LATC, 0\n"      // TRIG = 1
        "NOP\nNOP\nNOP\nNOP\nNOP\nNOP\nNOP\nNOP\nNOP\nNOP\n" // Délai 10µs
        "BCF LATC, 0\n"      // TRIG = 0
            
        // Attente front montant sur ECHO 
        "CLRF _timeout+1\n"       
        "MOVLW 0x30\n"           
        "MOVWF _timeout\n"

        "WAIT_RISE:\n"
        "BTFSS PORTC, 1\n"        // Test RC1 (ECHO) = 1 ?
        "GOTO DEC_TIMEOUT_RISE\n" // Sinon, décrémente timeout
        "GOTO RISE_DONE\n"        // Oui, sortie

        "DEC_TIMEOUT_RISE:\n"
        "DECFSZ _timeout, F\n"    
        "GOTO WAIT_RISE\n"
        "DECFSZ _timeout+1, F\n"
        "GOTO WAIT_RISE\n"

        "RISE_DONE:\n"
    );
    
    if(timeout==0) return 0;  

    // --- Démarrage Timer1 (en assembleur) ---
    __asm(
        "CLRF TMR1H\n"      // TMR1H = 0
        "CLRF TMR1L\n"      // TMR1L = 0
        "BSF  T1CON, 0\n"   // TMR1ON = 1 
    );
    
    timeout = 60000;
    
    // --- Attente front descendant ---
    __asm(
        "CLRF _timeout+1\n"     
        "MOVLW 0x60\n"          
        "MOVWF _timeout\n"

        "WAIT_FALL:\n"
        "BTFSC PORTC, 1\n"            // Test RC1 = 0 ?
            "GOTO DEC_TIMEOUT_FALL\n" // Non, décrémente timeout
        "GOTO FALL_DONE\n"            // Oui, sortie

        "DEC_TIMEOUT_FALL:\n"
        "DECFSZ _timeout, F\n"
        "GOTO WAIT_FALL\n"
        "DECFSZ _timeout+1, F\n"
        "GOTO WAIT_FALL\n"

        "FALL_DONE:\n"
    /*
    if(timeout==0) {           
        __asm("BCF T1CON, 0"); // Stop Timer1 si pas de front descendant
        return 0;              // Retourne 0si pas de front descendant
    }
    */
    // Lecture du résultat 
        "BCF T1CON, 0\n"             // arrêt Timer1
        "MOVFF TMR1H, _duration+1\n" // MSB
        "MOVFF TMR1L, _duration\n"   // LSB
    );
    return duration;
}

void CheckButton(char *button_pressed) {
    char button_state = 0;

    __asm(
        "MOVF PORTB, W\n"       // Lire PORTB dans le registre W
        "ANDLW 0x01\n"          // Isoler le bit 0 (RB0)
    );
    button_state = WREG; // button_state vaut 0 si pressé 

    if (button_state == 0 && *button_pressed == 0) {
        *button_pressed = 1; // Définir le drapeau
        
        putUSBUSART((uint8_t*)"FLAP\n", 5); // Envoyer les données 
    } 
    else if (button_state!= 0) {
        *button_pressed = 0; // Le bouton est relâché, effacer le drapeau
    }
}

void CheckSound(void) {
    uint16_t distance = MeasureEcho();  // Mesure capteur HC-SR04

    // Si distance dans plage, on déclenche le flap
    if (distance > SENSOR_DEADZONE && distance < FLAP_THRESHOLD)
    {
        putUSBUSART((uint8_t*)"FLAP\n", 5);
    }
    /*
    // Affichage debug distance
    char buf[32];
    sprintf(buf, "DIST=%u\r\n", distance);
    putUSBUSART((uint8_t*)buf, strlen(buf));
    */
}

void main(void) {  
    initUSBLib();
    InitializeSystem();
    char button_pressed = 0;
    
    while (1)
    {
        //if (isUSBReady()) { 
            USBDeviceTasks();
            if (USBGetDeviceState() < CONFIGURED_STATE || USBIsDeviceSuspended())
                continue;
            CheckButton(&button_pressed);
            CheckSound();
            CDCTxService();
            __delay_ms(60);
       // }
    }
}
