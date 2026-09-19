# Repository Coverage



| Name                                       |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------- | -------: | -------: | ------: | --------: |
| vortex/\_\_main\_\_.py                     |       11 |       11 |      0% |      3-20 |
| vortex/clinic/\_\_init\_\_.py              |        9 |        1 |     89% |        24 |
| vortex/clinic/client.py                    |      361 |       35 |     90% |188-190, 199, 204, 415, 427, 429, 434, 471, 475-479, 507, 656-666, 698-700, 714, 736, 821, 825, 1020 |
| vortex/clinic/fixtures.py                  |       28 |        0 |    100% |           |
| vortex/contract.py                         |      439 |       29 |     93% |944-947, 951, 960, 966-967, 973, 977-983, 987, 991-993, 1008, 1023, 1035, 1041, 1045, 1051, 1055, 1059, 1079 |
| vortex/conversation/language.py            |       71 |        5 |     93% |137-138, 186-187, 196 |
| vortex/conversation/prompt.py              |       94 |        1 |     99% |       153 |
| vortex/conversation/stt\_context.py        |       56 |        2 |     96% |   305-306 |
| vortex/conversation/turns.py               |      199 |        2 |     99% |  590, 646 |
| vortex/diary/rebooking.py                  |      262 |       30 |     89% |83, 88, 90, 98, 139, 233-237, 334, 366, 392-401, 406, 418, 439, 442, 444, 446, 448, 467, 477, 485 |
| vortex/diary/tools.py                      |      362 |       31 |     91% |249, 252, 332-333, 336, 356-359, 440, 457, 473, 475, 485, 547, 591, 619-620, 639-640, 757-758, 776-777, 821-822, 858, 877, 915-916, 987 |
| vortex/identity/dictation.py               |       79 |        3 |     96% |234, 245, 249 |
| vortex/identity/tools.py                   |      225 |       22 |     90% |161, 260-265, 295-300, 311, 320-322, 483, 487-490, 496, 539, 572, 589 |
| vortex/jev/arbiter.py                      |       19 |       11 |     42% | 32, 44-61 |
| vortex/jev/client.py                       |       43 |       30 |     30% |18-21, 25-43, 47-51, 55-63 |
| vortex/jev/policy.py                       |       20 |        1 |     95% |        30 |
| vortex/line/aic\_filter.py                 |       22 |        1 |     95% |        45 |
| vortex/line/gemini\_live\_voice.py         |       92 |       56 |     39% |102-106, 124-226, 231-251 |
| vortex/line/llm\_timeout.py                |      140 |        3 |     98% |240, 289, 302 |
| vortex/line/pipecat\_voice.py              |      377 |       98 |     74% |135-136, 213-409, 413, 555, 558, 609, 733, 743, 752, 804-807, 822, 835-836, 994-1007, 1009-1010, 1012, 1029 |
| vortex/line/privacy.py                     |       72 |        5 |     93% |94, 118, 121, 127, 187 |
| vortex/line/server.py                      |      120 |       30 |     75% |52-54, 63-64, 70, 114, 128, 133, 142, 148, 155-160, 168-170, 178-180, 182-184, 189-194 |
| vortex/line/session.py                     |      480 |       34 |     93% |479, 588, 610, 631, 633, 636, 680-682, 689, 732, 775-777, 784, 821-826, 839-844, 864-865, 875-876, 927, 962, 1003, 1036, 1071-1076, 1079 |
| vortex/line/smart\_turn\_ab.py             |      152 |        7 |     95% |115, 126, 198-200, 208, 212 |
| vortex/line/sms.py                         |      170 |       20 |     88% |113, 142-143, 145, 165, 197-202, 217-222, 285-286, 300, 302, 320 |
| vortex/line/sms\_reminders.py              |      204 |       51 |     75% |48, 67, 89-91, 93, 97, 100-101, 141, 143-146, 149, 165, 168-171, 173, 207, 210, 266, 303-306, 309-317, 320-333, 352-358, 365 |
| vortex/line/soniox\_stall.py               |      109 |       21 |     81% |91-92, 95-97, 111, 113, 144, 180-188, 196-197, 203-204 |
| vortex/line/stub\_voice.py                 |       44 |        7 |     84% | 34, 61-66 |
| vortex/line/submit.py                      |       86 |       23 |     73% |59, 66-84, 87, 148, 155 |
| vortex/line/twilio.py                      |       77 |        3 |     96% |61, 153, 160 |
| vortex/line/ulaw.py                        |       48 |       11 |     77% |33-39, 52-55 |
| vortex/line/usage.py                       |       64 |        5 |     92% |152-154, 169, 171 |
| vortex/line/voice\_config.py               |      101 |       21 |     79% |61, 104-106, 154-158, 167, 169, 190-215 |
| vortex/models.py                           |       83 |        3 |     96% |88-90, 162 |
| vortex/observability/\_\_init\_\_.py       |        3 |        0 |    100% |           |
| vortex/observability/agents.py             |       24 |        0 |    100% |           |
| vortex/observability/auth.py               |       33 |        2 |     94% |    28, 30 |
| vortex/observability/business\_insights.py |      599 |       55 |     91% |136-138, 161-164, 399, 402-403, 409-410, 420, 423-424, 447-454, 461-462, 468, 473, 475, 540, 544-545, 547, 562, 608, 666-668, 680-681, 712, 805, 811, 814-815, 1002, 1005-1006, 1008, 1019-1020, 1168-1170, 1184-1185 |
| vortex/observability/calendar.py           |      620 |       61 |     90% |156-157, 159, 199, 224, 247, 249, 268, 305, 422, 433, 525, 528-529, 532-537, 552, 568, 590, 593-594, 618-620, 635, 700, 720-721, 724, 761, 770, 772, 774, 948, 952, 976, 1030-1031, 1066, 1072, 1074, 1140, 1148, 1175, 1203, 1205-1207, 1212, 1218, 1220, 1255, 1302-1304, 1324-1328 |
| vortex/observability/calendar\_view.py     |      255 |       39 |     85% |51, 77, 83, 87, 110-112, 119, 124, 128, 130, 147, 208, 216, 226-229, 249-252, 320-324, 327-331, 334-335, 338-340, 365-367 |
| vortex/observability/callfeed.py           |       53 |        0 |    100% |           |
| vortex/observability/calllog.py            |      149 |       13 |     91% |49-51, 153, 158-159, 177, 208, 228-229, 238, 243-244 |
| vortex/observability/console.py            |      420 |       41 |     90% |36-37, 57, 67, 77, 88, 99, 158-163, 206, 229, 306, 346, 361-363, 417, 480, 509, 517-518, 522-523, 541-545, 572, 593-595, 664, 678, 755-756, 763, 852 |
| vortex/observability/demo.py               |      176 |        4 |     98% |726, 735, 738-739 |
| vortex/observability/discord\_calls.py     |      168 |       53 |     68% |80, 89, 95, 105, 108, 172, 178, 243, 254, 277-305, 311-316, 320-341, 345 |
| vortex/observability/explain.py            |      333 |       63 |     81% |150, 172, 181, 183-184, 194, 196, 198, 201, 207, 227-229, 252-264, 348, 390-393, 445-451, 480, 483-485, 492, 513-532, 538, 611, 613-620, 633, 676 |
| vortex/observability/home\_overview.py     |      141 |      100 |     29% |69-73, 77-83, 87-94, 100-101, 119-133, 145-162, 179-187, 212-217, 223, 234-241, 245-271, 275, 279, 288-291 |
| vortex/observability/icons.py              |       12 |        0 |    100% |           |
| vortex/observability/insights.py           |      154 |       11 |     93% |34, 77, 80-81, 86, 116, 132-133, 221, 241, 251 |
| vortex/observability/langfuse\_status.py   |      101 |      101 |      0% |     3-151 |
| vortex/observability/live.py               |      997 |      270 |     73% |94, 97-98, 103-108, 116-117, 174, 185-203, 207-212, 216-227, 250, 261, 268, 276, 296-298, 304, 309, 314, 317, 323-324, 369-370, 414, 445, 449, 464-467, 477-481, 494-497, 524, 543-544, 589, 650, 656, 681, 685-687, 691-694, 719, 728-745, 758-761, 814-822, 871-873, 942-947, 960, 963-964, 992-996, 1000, 1006-1020, 1032-1034, 1041-1044, 1057-1097, 1108-1110, 1117, 1124, 1135-1141, 1146-1151, 1157-1167, 1175, 1184, 1192, 1203-1206, 1210-1226, 1250-1251, 1257, 1267-1268, 1342-1343, 1346-1347, 1380-1382, 1415-1428, 1441-1475, 1480, 1499-1504, 1509, 1532, 1537 |
| vortex/observability/pricing.py            |       95 |        3 |     97% |49-50, 229 |
| vortex/observability/replay.py             |       86 |       51 |     41% |44-45, 49-51, 67-87, 104, 127, 148-180 |
| vortex/observability/shell.py              |      110 |        4 |     96% |133-134, 146-147 |
| vortex/observability/tracing.py            |      262 |       49 |     81% |188-198, 202-214, 243, 258-261, 281-287, 295, 323, 348, 351, 380, 436, 438, 440, 442, 444, 456-477, 485, 500-501, 516, 551 |
| vortex/observability/view.py               |      281 |       19 |     93% |73, 75, 79, 97, 106, 117, 126, 128, 131, 160, 179-180, 189, 199, 232-233, 279-280, 311 |
| vortex/observability/wall\_timeline.py     |       79 |       68 |     14% |20-94, 106-114, 118, 127-138, 142, 150-153, 164-177 |
| vortex/rules/eligibility.py                |       99 |       15 |     85% |90, 93, 126, 144, 148, 159, 237, 291-304, 310, 313-315 |
| vortex/rules/facts.py                      |       84 |        2 |     98% |  200, 202 |
| vortex/rules/geo.py                        |      103 |       11 |     89% |239, 242-243, 255-257, 273, 279, 289-290, 338 |
| vortex/rules/tools.py                      |      180 |       17 |     91% |134, 180-181, 229-236, 360, 368, 501, 525, 564, 570 |
| vortex/rules/triage.py                     |       62 |        1 |     98% |       259 |
| vortex/settings.py                         |      240 |        4 |     98% |111-112, 435, 587 |
| vortex/tools.py                            |       93 |        7 |     92% |257, 264, 275-277, 279, 298 |
| **TOTAL**                                  | **10731** | **1677** | **84%** |           |

7 empty files skipped.


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://github.com/jferreiros/vortex/raw/python-coverage-comment-action-data/badge.svg)](https://github.com/jferreiros/vortex/tree/python-coverage-comment-action-data)

This is the one to use if your repository is private or if you don't want to customize anything.



## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.