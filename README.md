# Repository Coverage



| Name                                       |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------- | -------: | -------: | ------: | --------: |
| vortex/\_\_main\_\_.py                     |       11 |       11 |      0% |      3-20 |
| vortex/clinic/\_\_init\_\_.py              |        9 |        1 |     89% |        24 |
| vortex/clinic/client.py                    |      272 |       71 |     74% |70, 107-109, 132, 149-151, 160, 165, 373-377, 388, 390, 395, 402-408, 411-415, 418-422, 425-429, 439-450, 463-485, 490-493, 496, 507-517, 539-541, 552, 608, 612, 767 |
| vortex/clinic/fixtures.py                  |       28 |        0 |    100% |           |
| vortex/contract.py                         |      438 |       29 |     93% |939-942, 946, 955, 961-962, 968, 972-978, 982, 986-988, 1003, 1018, 1030, 1036, 1040, 1046, 1050, 1054, 1074 |
| vortex/conversation/language.py            |       71 |        7 |     90% |137-138, 186-187, 195-199 |
| vortex/conversation/prompt.py              |       94 |        1 |     99% |       153 |
| vortex/conversation/stt\_context.py        |       56 |        2 |     96% |   305-306 |
| vortex/conversation/turns.py               |      199 |        2 |     99% |  590, 646 |
| vortex/diary/rebooking.py                  |      262 |       30 |     89% |83, 88, 90, 98, 139, 233-237, 334, 366, 392-401, 406, 418, 439, 442, 444, 446, 448, 467, 477, 485 |
| vortex/diary/tools.py                      |      326 |       32 |     90% |249, 252, 322-323, 332-333, 336, 346-349, 407, 423, 425, 435, 497, 541, 569-570, 589-590, 701-702, 745-746, 754-755, 761, 782, 830-831, 902 |
| vortex/identity/dictation.py               |       79 |        3 |     96% |234, 245, 249 |
| vortex/identity/tools.py                   |      225 |       22 |     90% |161, 260-265, 295-300, 311, 320-322, 483, 487-490, 496, 539, 572, 589 |
| vortex/jev/arbiter.py                      |       19 |       19 |      0% |      1-61 |
| vortex/jev/client.py                       |       43 |       43 |      0% |      1-63 |
| vortex/jev/policy.py                       |       20 |        1 |     95% |        30 |
| vortex/line/aic\_filter.py                 |       22 |        1 |     95% |        45 |
| vortex/line/gemini\_live\_voice.py         |       92 |       56 |     39% |102-106, 124-226, 231-251 |
| vortex/line/llm\_timeout.py                |      140 |        3 |     98% |240, 289, 302 |
| vortex/line/pipecat\_voice.py              |      327 |       99 |     70% |115-116, 170-370, 374, 480, 483, 534, 658, 668, 677, 729-732, 747, 760-761, 886-905 |
| vortex/line/privacy.py                     |       72 |        5 |     93% |94, 118, 121, 127, 187 |
| vortex/line/server.py                      |      104 |       27 |     74% |50-52, 90, 104, 109, 118, 124, 131-136, 144-146, 154-156, 158-160, 165-170 |
| vortex/line/session.py                     |      348 |       14 |     96% |397, 497, 519, 540, 542, 545, 589-591, 598, 639, 709, 744, 785 |
| vortex/line/smart\_turn\_ab.py             |      152 |        7 |     95% |115, 126, 198-200, 208, 212 |
| vortex/line/stub\_voice.py                 |       44 |        7 |     84% | 34, 61-66 |
| vortex/line/submit.py                      |       68 |       27 |     60% |44, 51-69, 72, 127, 130-139 |
| vortex/line/twilio.py                      |       77 |        3 |     96% |61, 153, 160 |
| vortex/line/ulaw.py                        |       48 |       11 |     77% |33-39, 52-55 |
| vortex/line/usage.py                       |       64 |        5 |     92% |152-154, 169, 171 |
| vortex/line/voice\_config.py               |      101 |       21 |     79% |61, 104-106, 154-158, 167, 169, 190-215 |
| vortex/models.py                           |       83 |        3 |     96% |88-90, 162 |
| vortex/observability/\_\_init\_\_.py       |        3 |        0 |    100% |           |
| vortex/observability/agents.py             |       24 |        0 |    100% |           |
| vortex/observability/auth.py               |       33 |        2 |     94% |    28, 30 |
| vortex/observability/business\_insights.py |      361 |       49 |     86% |114-116, 138-141, 340, 350, 354, 357-358, 364-365, 375, 378-379, 398-405, 412-413, 419, 424, 426, 477, 481-482, 484, 499, 533, 565, 571, 574-575, 662, 665-666, 682-684, 695, 698-699 |
| vortex/observability/calendar.py           |      212 |       20 |     91% |114-115, 117, 174, 291, 302, 390, 393-394, 397-402, 417, 433, 455, 458-459 |
| vortex/observability/calendar\_view.py     |      111 |        8 |     93% |47, 90-93, 134-135, 144 |
| vortex/observability/callfeed.py           |       53 |        0 |    100% |           |
| vortex/observability/calllog.py            |      149 |       14 |     91% |49-51, 95, 153, 158-159, 177, 208, 228-229, 238, 243-244 |
| vortex/observability/console.py            |      420 |       41 |     90% |36-37, 57, 67, 77, 88, 99, 158-163, 206, 229, 306, 346, 361-363, 417, 480, 509, 517-518, 522-523, 541-545, 572, 593-595, 664, 678, 755-756, 763, 852 |
| vortex/observability/demo.py               |      155 |        4 |     97% |567, 576, 579-580 |
| vortex/observability/discord\_calls.py     |      168 |       53 |     68% |80, 89, 95, 105, 108, 172, 178, 243, 254, 277-305, 311-316, 320-341, 345 |
| vortex/observability/explain.py            |      333 |       63 |     81% |150, 172, 181, 183-184, 194, 196, 198, 201, 207, 227-229, 252-264, 348, 390-393, 445-451, 480, 483-485, 492, 513-532, 538, 611, 613-620, 633, 676 |
| vortex/observability/home\_overview.py     |      141 |      100 |     29% |69-73, 77-83, 87-94, 100-101, 119-133, 145-162, 179-187, 212-217, 223, 234-241, 245-271, 275, 279, 288-291 |
| vortex/observability/icons.py              |       12 |        0 |    100% |           |
| vortex/observability/insights.py           |      154 |       11 |     93% |34, 77, 80-81, 86, 116, 132-133, 221, 241, 251 |
| vortex/observability/langfuse\_status.py   |      101 |      101 |      0% |     3-151 |
| vortex/observability/live.py               |      929 |      220 |     76% |92, 95-96, 101-106, 114-115, 172, 183-201, 205-210, 214-225, 248, 256-260, 266, 274, 294-296, 302, 307, 312, 315, 321-322, 367-368, 412, 443, 447, 462-465, 475-479, 492-495, 522, 541-542, 587, 648, 654, 679, 683-685, 689-692, 717, 726-743, 756-759, 812-820, 869-871, 940-945, 958, 961-962, 997-999, 1006, 1013, 1024-1030, 1035-1040, 1046-1056, 1064, 1073, 1081, 1092-1095, 1099-1115, 1139-1140, 1146, 1156-1157, 1231-1232, 1235-1236, 1269-1271, 1304-1317, 1330-1364, 1369, 1388-1393, 1398, 1421, 1426 |
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
| vortex/settings.py                         |      228 |        4 |     98% |111-112, 392, 544 |
| vortex/tools.py                            |       93 |        7 |     92% |257, 264, 275-277, 279, 298 |
| **TOTAL**                                  | **9015** | **1500** | **83%** |           |

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