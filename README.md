# Repository Coverage



| Name                                       |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------- | -------: | -------: | ------: | --------: |
| vortex/\_\_main\_\_.py                     |       11 |       11 |      0% |      3-20 |
| vortex/clinic/\_\_init\_\_.py              |        9 |        1 |     89% |        24 |
| vortex/clinic/client.py                    |      272 |       71 |     74% |70, 107-109, 132, 149-151, 160, 165, 373-377, 388, 390, 395, 402-408, 411-415, 418-422, 425-429, 439-450, 463-485, 490-493, 496, 507-517, 539-541, 552, 608, 612, 767 |
| vortex/clinic/fixtures.py                  |       28 |        0 |    100% |           |
| vortex/contract.py                         |      434 |       29 |     93% |925-928, 932, 941, 947-948, 954, 958-964, 968, 972-974, 989, 1004, 1016, 1022, 1026, 1032, 1036, 1040, 1060 |
| vortex/conversation/language.py            |       71 |        7 |     90% |137-138, 186-187, 195-199 |
| vortex/conversation/prompt.py              |       59 |        0 |    100% |           |
| vortex/conversation/stt\_context.py        |       56 |        2 |     96% |   305-306 |
| vortex/conversation/turns.py               |      172 |        1 |     99% |       571 |
| vortex/diary/rebooking.py                  |      262 |       30 |     89% |83, 88, 90, 98, 139, 233-237, 334, 366, 392-401, 406, 418, 439, 442, 444, 446, 448, 467, 477, 485 |
| vortex/diary/tools.py                      |      313 |       30 |     90% |248, 251, 321-322, 331-332, 335, 345-348, 406, 422, 424, 434, 496, 532, 556-557, 673-674, 717-718, 726-727, 733, 754, 802-803, 874 |
| vortex/identity/dictation.py               |       79 |        3 |     96% |234, 245, 249 |
| vortex/identity/tools.py                   |      225 |       22 |     90% |161, 260-265, 295-300, 311, 320-322, 483, 487-490, 496, 539, 572, 589 |
| vortex/line/aic\_filter.py                 |       22 |        1 |     95% |        45 |
| vortex/line/gemini\_live\_voice.py         |       92 |       56 |     39% |102-106, 124-226, 231-251 |
| vortex/line/llm\_timeout.py                |      124 |        2 |     98% |  259, 272 |
| vortex/line/pipecat\_voice.py              |      294 |       96 |     67% |113-114, 168-353, 357, 459, 624, 634, 643, 693-696, 722-723, 800-828 |
| vortex/line/privacy.py                     |       72 |        5 |     93% |94, 118, 121, 127, 187 |
| vortex/line/server.py                      |       77 |       20 |     74% |48-50, 68-69, 74, 79, 87-89, 97-99, 101-103, 108-113 |
| vortex/line/session.py                     |      321 |       10 |     97% |386, 486, 530-532, 539, 580, 645, 680, 721 |
| vortex/line/smart\_turn\_ab.py             |      152 |        7 |     95% |115, 126, 198-200, 208, 212 |
| vortex/line/stub\_voice.py                 |       44 |        7 |     84% | 34, 61-66 |
| vortex/line/submit.py                      |       61 |       22 |     64% |43, 50-68, 71, 126 |
| vortex/line/twilio.py                      |       77 |        3 |     96% |61, 153, 160 |
| vortex/line/ulaw.py                        |       48 |       11 |     77% |33-39, 52-55 |
| vortex/models.py                           |       83 |        3 |     96% |88-90, 162 |
| vortex/observability/\_\_init\_\_.py       |        3 |        0 |    100% |           |
| vortex/observability/agents.py             |       24 |        0 |    100% |           |
| vortex/observability/auth.py               |       33 |        2 |     94% |    28, 30 |
| vortex/observability/business\_insights.py |      361 |       52 |     86% |114-116, 138-141, 340, 350, 354, 357-358, 364-365, 374-375, 378-379, 398-405, 412-413, 419, 424, 426, 477, 481-482, 484, 499, 533, 565, 571, 574-575, 652, 662, 665-666, 677, 682-684, 695, 698-699 |
| vortex/observability/calendar.py           |      212 |       20 |     91% |114-115, 117, 174, 291, 302, 390, 393-394, 397-402, 417, 433, 455, 458-459 |
| vortex/observability/calendar\_view.py     |      111 |        8 |     93% |47, 90-93, 134-135, 144 |
| vortex/observability/calllog.py            |       73 |       11 |     85% |48-50, 94, 128, 135-136, 141-144 |
| vortex/observability/console.py            |      411 |       41 |     90% |36-37, 57, 67, 77, 88, 99, 158-163, 206, 229, 306, 346, 361-363, 417, 456, 485, 493-494, 498-499, 517-521, 548, 569-571, 640, 654, 731-732, 739, 828 |
| vortex/observability/demo.py               |       61 |        0 |    100% |           |
| vortex/observability/discord\_calls.py     |      168 |       53 |     68% |77, 86, 92, 102, 105, 169, 175, 240, 251, 274-302, 308-313, 317-338, 342 |
| vortex/observability/explain.py            |      325 |       63 |     81% |150, 172, 181, 183-184, 194, 196, 198, 201, 207, 227-229, 252-264, 336, 378-381, 432-438, 467, 470-472, 479, 500-519, 525, 598, 600-607, 620, 663 |
| vortex/observability/icons.py              |       12 |        0 |    100% |           |
| vortex/observability/insights.py           |      109 |        8 |     93% |32, 75, 78-79, 84, 135, 155, 165 |
| vortex/observability/langfuse\_status.py   |      101 |      101 |      0% |     3-151 |
| vortex/observability/live.py               |      849 |      191 |     78% |73-79, 87, 90-91, 96-101, 109-110, 167, 178-196, 200, 223, 229, 234, 241, 249, 269-271, 277, 282, 287, 290, 296-297, 342-343, 405, 409, 424-427, 437-441, 454-457, 484, 503-504, 585, 591, 616, 620-622, 626-629, 654, 663-680, 693-696, 743-751, 800-802, 871-876, 888-894, 903-911, 919, 928, 939-942, 946-962, 986-987, 993, 1003-1004, 1075-1076, 1079-1080, 1113-1115, 1148-1161, 1174-1208, 1213, 1232-1237, 1242, 1252 |
| vortex/observability/replay.py             |       86 |       86 |      0% |    18-180 |
| vortex/observability/shell.py              |      110 |        4 |     96% |133-134, 146-147 |
| vortex/observability/tracing.py            |      262 |       49 |     81% |188-198, 202-214, 243, 258-261, 281-287, 295, 323, 348, 351, 380, 436, 438, 440, 442, 444, 456-477, 485, 500-501, 516, 551 |
| vortex/observability/view.py               |      278 |       24 |     91% |69, 71, 75, 93, 102, 113, 122, 124, 127, 156, 175-176, 185, 195, 228-229, 275-276, 305, 325-329 |
| vortex/observability/wall\_timeline.py     |       79 |       68 |     14% |20-94, 106-114, 118, 127-138, 142, 150-153, 164-177 |
| vortex/rules/eligibility.py                |       99 |       15 |     85% |90, 93, 126, 144, 148, 159, 237, 291-304, 310, 313-315 |
| vortex/rules/facts.py                      |       84 |        2 |     98% |  200, 202 |
| vortex/rules/geo.py                        |      103 |       11 |     89% |239, 242-243, 255-257, 273, 279, 289-290, 338 |
| vortex/rules/tools.py                      |      180 |       17 |     91% |134, 180-181, 229-236, 360, 368, 501, 525, 564, 570 |
| vortex/rules/triage.py                     |       62 |        1 |     98% |       259 |
| vortex/settings.py                         |      214 |        2 |     99% |  365, 517 |
| vortex/tools.py                            |       93 |        7 |     92% |257, 264, 275-277, 279, 298 |
| **TOTAL**                                  | **7961** | **1286** | **84%** |           |

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