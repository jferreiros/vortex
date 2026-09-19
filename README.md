# Repository Coverage



| Name                                       |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------- | -------: | -------: | ------: | --------: |
| vortex/\_\_main\_\_.py                     |       11 |       11 |      0% |      3-20 |
| vortex/clinic/\_\_init\_\_.py              |        9 |        1 |     89% |        24 |
| vortex/clinic/client.py                    |      272 |       71 |     74% |70, 107-109, 132, 149-151, 160, 165, 373-377, 388, 390, 395, 402-408, 411-415, 418-422, 425-429, 439-450, 463-485, 490-493, 496, 507-517, 539-541, 552, 608, 612, 767 |
| vortex/clinic/fixtures.py                  |       28 |        0 |    100% |           |
| vortex/contract.py                         |      438 |       29 |     93% |939-942, 946, 955, 961-962, 968, 972-978, 982, 986-988, 1003, 1018, 1030, 1036, 1040, 1046, 1050, 1054, 1074 |
| vortex/conversation/language.py            |       71 |        7 |     90% |137-138, 186-187, 195-199 |
| vortex/conversation/prompt.py              |       60 |        0 |    100% |           |
| vortex/conversation/stt\_context.py        |       56 |        2 |     96% |   305-306 |
| vortex/conversation/turns.py               |      185 |        2 |     99% |  567, 623 |
| vortex/diary/rebooking.py                  |      262 |       30 |     89% |83, 88, 90, 98, 139, 233-237, 334, 366, 392-401, 406, 418, 439, 442, 444, 446, 448, 467, 477, 485 |
| vortex/diary/tools.py                      |      326 |       32 |     90% |249, 252, 322-323, 332-333, 336, 346-349, 407, 423, 425, 435, 497, 541, 569-570, 589-590, 701-702, 745-746, 754-755, 761, 782, 830-831, 902 |
| vortex/identity/dictation.py               |       79 |        3 |     96% |234, 245, 249 |
| vortex/identity/tools.py                   |      225 |       22 |     90% |161, 260-265, 295-300, 311, 320-322, 483, 487-490, 496, 539, 572, 589 |
| vortex/line/aic\_filter.py                 |       22 |        1 |     95% |        45 |
| vortex/line/gemini\_live\_voice.py         |       92 |       56 |     39% |102-106, 124-226, 231-251 |
| vortex/line/llm\_timeout.py                |      140 |        3 |     98% |240, 289, 302 |
| vortex/line/pipecat\_voice.py              |      316 |       92 |     71% |114-115, 169-363, 367, 469, 634, 644, 653, 703-706, 732-733, 858-877 |
| vortex/line/privacy.py                     |       72 |        5 |     93% |94, 118, 121, 127, 187 |
| vortex/line/server.py                      |       77 |       20 |     74% |48-50, 68-69, 74, 79, 87-89, 97-99, 101-103, 108-113 |
| vortex/line/session.py                     |      343 |       15 |     96% |391, 491, 511, 513, 526, 528, 531, 572-574, 581, 622, 692, 727, 768 |
| vortex/line/smart\_turn\_ab.py             |      152 |        7 |     95% |115, 126, 198-200, 208, 212 |
| vortex/line/stub\_voice.py                 |       44 |        7 |     84% | 34, 61-66 |
| vortex/line/submit.py                      |       61 |       22 |     64% |43, 50-68, 71, 126 |
| vortex/line/twilio.py                      |       77 |        3 |     96% |61, 153, 160 |
| vortex/line/ulaw.py                        |       48 |       11 |     77% |33-39, 52-55 |
| vortex/line/usage.py                       |       64 |        5 |     92% |152-154, 169, 171 |
| vortex/models.py                           |       83 |        3 |     96% |88-90, 162 |
| vortex/observability/\_\_init\_\_.py       |        3 |        0 |    100% |           |
| vortex/observability/agents.py             |       24 |        0 |    100% |           |
| vortex/observability/auth.py               |       33 |        2 |     94% |    28, 30 |
| vortex/observability/business\_insights.py |      361 |       52 |     86% |114-116, 138-141, 340, 350, 354, 357-358, 364-365, 374-375, 378-379, 398-405, 412-413, 419, 424, 426, 477, 481-482, 484, 499, 533, 565, 571, 574-575, 652, 662, 665-666, 677, 682-684, 695, 698-699 |
| vortex/observability/calendar.py           |      212 |       20 |     91% |114-115, 117, 174, 291, 302, 390, 393-394, 397-402, 417, 433, 455, 458-459 |
| vortex/observability/calendar\_view.py     |      111 |        8 |     93% |47, 90-93, 134-135, 144 |
| vortex/observability/calllog.py            |       73 |       11 |     85% |48-50, 94, 128, 135-136, 141-144 |
| vortex/observability/console.py            |      420 |       41 |     90% |36-37, 57, 67, 77, 88, 99, 158-163, 206, 229, 306, 346, 361-363, 417, 480, 509, 517-518, 522-523, 541-545, 572, 593-595, 664, 678, 755-756, 763, 852 |
| vortex/observability/demo.py               |       65 |        0 |    100% |           |
| vortex/observability/discord\_calls.py     |      168 |       53 |     68% |80, 89, 95, 105, 108, 172, 178, 243, 254, 277-305, 311-316, 320-341, 345 |
| vortex/observability/explain.py            |      333 |       63 |     81% |150, 172, 181, 183-184, 194, 196, 198, 201, 207, 227-229, 252-264, 348, 390-393, 445-451, 480, 483-485, 492, 513-532, 538, 611, 613-620, 633, 676 |
| vortex/observability/icons.py              |       12 |        0 |    100% |           |
| vortex/observability/insights.py           |      154 |       11 |     93% |34, 77, 80-81, 86, 116, 132-133, 221, 241, 251 |
| vortex/observability/langfuse\_status.py   |      101 |      101 |      0% |     3-151 |
| vortex/observability/live.py               |      879 |      199 |     77% |96-104, 108, 114, 117-118, 123-128, 136-137, 194, 205-223, 227, 250, 258-262, 268, 276, 296-298, 304, 309, 314, 317, 323-324, 369-370, 414, 445, 449, 464-467, 477-481, 494-497, 524, 543-544, 589, 650, 656, 681, 685-687, 691-694, 719, 728-745, 758-761, 814-822, 871-873, 942-947, 959-965, 974-982, 990, 999, 1010-1013, 1017-1033, 1057-1058, 1064, 1074-1075, 1146-1147, 1150-1151, 1184-1186, 1219-1232, 1245-1279, 1284, 1303-1308, 1313, 1323 |
| vortex/observability/pricing.py            |       95 |        3 |     97% |49-50, 229 |
| vortex/observability/replay.py             |       86 |       86 |      0% |    18-180 |
| vortex/observability/shell.py              |      110 |        4 |     96% |133-134, 146-147 |
| vortex/observability/tracing.py            |      262 |       49 |     81% |188-198, 202-214, 243, 258-261, 281-287, 295, 323, 348, 351, 380, 436, 438, 440, 442, 444, 456-477, 485, 500-501, 516, 551 |
| vortex/observability/view.py               |      281 |       24 |     91% |73, 75, 79, 97, 106, 117, 126, 128, 131, 160, 179-180, 189, 199, 232-233, 279-280, 311, 331-335 |
| vortex/observability/wall\_timeline.py     |       79 |       68 |     14% |20-94, 106-114, 118, 127-138, 142, 150-153, 164-177 |
| vortex/rules/eligibility.py                |       99 |       15 |     85% |90, 93, 126, 144, 148, 159, 237, 291-304, 310, 313-315 |
| vortex/rules/facts.py                      |       84 |        2 |     98% |  200, 202 |
| vortex/rules/geo.py                        |      103 |       11 |     89% |239, 242-243, 255-257, 273, 279, 289-290, 338 |
| vortex/rules/tools.py                      |      180 |       17 |     91% |134, 180-181, 229-236, 360, 368, 501, 525, 564, 570 |
| vortex/rules/triage.py                     |       62 |        1 |     98% |       259 |
| vortex/settings.py                         |      227 |        4 |     98% |111-112, 391, 543 |
| vortex/tools.py                            |       93 |        7 |     92% |257, 264, 275-277, 279, 298 |
| **TOTAL**                                  | **8323** | **1312** | **84%** |           |

6 empty files skipped.


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