# Dataset v2 summary

seed 1, imgsz hint 736, generated in 427.7 s

| | train | val | test |
|---|---|---|---|
| images | 2000 | 300 | 300 |
| labels | 34682 | 5167 | 5327 |
| long side px (min/median/max) | 247/779.5/1902 | 283/753.0/1699 | 324/796.5/1683 |
| smallest contact at imgsz, px (min/p05/median) | 13.34/14.72/17.25 | 13.44/14.7/17.11 | 13.52/14.69/16.93 |

## Styles, platforms, augmentation (train)

styles: {"studio5000": 383, "rslogix500": 580, "dark": 240, "tia": 294, "printed": 237, "iec": 266}

platforms: {"rockwell_logix": 554, "rockwell_slc": 688, "siemens_tia": 453, "generic_iec": 305}

augmentation: {"light": 819, "none": 673, "heavy": 508}

## Class histogram

| id | class | train | val | test |
|---|---|---|---|---|
| 0 | NO_Contact | 8828 | 1322 | 1376 |
| 1 | NC_Contact | 3686 | 541 | 571 |
| 2 | Positive_Transition | 329 | 59 | 52 |
| 3 | Negative_Transition | 255 | 33 | 45 |
| 4 | Output_Coil | 2720 | 393 | 422 |
| 5 | Negated_Coil | 338 | 44 | 52 |
| 6 | Set_Coil | 702 | 117 | 99 |
| 7 | Reset_Coil | 655 | 98 | 81 |
| 8 | TON_Timer | 253 | 35 | 33 |
| 9 | TOF_Timer | 246 | 34 | 36 |
| 10 | RTO_Timer | 247 | 46 | 39 |
| 11 | TP_Timer | 216 | 31 | 26 |
| 12 | CTU_Counter | 248 | 36 | 45 |
| 13 | CTD_Counter | 248 | 33 | 40 |
| 14 | CTUD_Counter | 217 | 33 | 25 |
| 15 | RES_Reset | 255 | 41 | 46 |
| 16 | EQU_Equal | 254 | 33 | 37 |
| 17 | NEQ_NotEqual | 242 | 30 | 42 |
| 18 | GRT_GreaterThan | 216 | 38 | 31 |
| 19 | LES_LessThan | 260 | 37 | 42 |
| 20 | GEQ_GreaterEqual | 212 | 32 | 35 |
| 21 | LEQ_LessEqual | 207 | 25 | 37 |
| 22 | ADD_Addition | 204 | 40 | 33 |
| 23 | SUB_Subtraction | 194 | 38 | 38 |
| 24 | MUL_Multiplication | 195 | 30 | 20 |
| 25 | DIV_Division | 240 | 26 | 27 |
| 26 | MOV_Move | 589 | 99 | 86 |
| 27 | OSR_OneShotRising | 238 | 51 | 44 |
| 28 | OSF_OneShotFalling | 219 | 27 | 34 |
| 29 | AND_Bitwise | 232 | 36 | 26 |
| 30 | OR_Bitwise | 229 | 38 | 37 |
| 31 | XOR_Bitwise | 229 | 36 | 34 |
| 32 | NOT_Bitwise | 300 | 53 | 51 |
| 33 | JMP_Jump | 271 | 37 | 45 |
| 34 | LBL_Label | 252 | 38 | 39 |
| 35 | JSR_Subroutine | 329 | 60 | 40 |
| 36 | MCR_MasterControl | 246 | 37 | 39 |
| 37 | END_End | 431 | 54 | 68 |
| 38 | Horizontal_Wire | 0 | 0 | 0 |
| 39 | Vertical_Wire | 0 | 0 | 0 |
| 40 | Branch_Start | 2725 | 388 | 427 |
| 41 | Branch_End | 2725 | 388 | 427 |
| 42 | Power_Rail_Left | 2000 | 300 | 300 |
| 43 | Power_Rail_Right | 2000 | 300 | 300 |

Rarest symbol class in train: **SUB_Subtraction** (194). Classes 38/39 (wires) are never labelled.
