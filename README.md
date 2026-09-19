# Repository Coverage



| Name                                   |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------- | -------: | -------: | ------: | --------: |
| vortex/\_\_main\_\_.py                 |       11 |       11 |      0% |      3-20 |
| vortex/clinic/\_\_init\_\_.py          |        9 |        1 |     89% |        24 |
| vortex/clinic/client.py                |      252 |       60 |     76% |68, 105-107, 130, 147-149, 158, 163, 349-351, 371-375, 386, 388, 393, 400-406, 409-413, 416-420, 423-427, 437-448, 461-483, 488-491, 494, 520, 576, 580, 735 |
| vortex/clinic/fixtures.py              |       28 |        0 |    100% |           |
| vortex/contract.py                     |      432 |       29 |     93% |916-919, 923, 932, 938-939, 945, 949-955, 959, 963-965, 980, 995, 1007, 1013, 1017, 1023, 1027, 1031, 1051 |
| vortex/conversation/language.py        |       71 |        7 |     90% |137-138, 186-187, 195-199 |
| vortex/conversation/prompt.py          |       59 |        0 |    100% |           |
| vortex/conversation/stt\_context.py    |       56 |        2 |     96% |   305-306 |
| vortex/conversation/turns.py           |      151 |        1 |     99% |       518 |
| vortex/diary/rebooking.py              |      252 |       33 |     87% |82, 87, 89, 99, 140, 234-238, 319, 321, 348, 374-383, 388, 400, 421, 424, 426, 428, 430, 449, 459, 466-468 |
| vortex/diary/tools.py                  |      311 |       30 |     90% |248, 251, 321-322, 331-332, 335, 345-348, 406, 422, 424, 434, 496, 532, 556-557, 666-667, 710-711, 719-720, 726, 747, 795-796, 867 |
| vortex/identity/dictation.py           |       79 |        3 |     96% |234, 245, 249 |
| vortex/identity/tools.py               |      234 |       26 |     89% |160, 271-276, 306-311, 313-327, 331-333, 494, 498-501, 507, 556, 589, 606 |
| vortex/line/aic\_filter.py             |       22 |        1 |     95% |        45 |
| vortex/line/gemini\_live\_voice.py     |       92 |       56 |     39% |102-106, 124-226, 231-251 |
| vortex/line/llm\_timeout.py            |      124 |        2 |     98% |  259, 272 |
| vortex/line/pipecat\_voice.py          |      271 |      102 |     62% |112-113, 120-321, 325, 427, 578, 628-631, 657-658, 735-763 |
| vortex/line/privacy.py                 |       72 |        5 |     93% |61, 85, 88, 94, 154 |
| vortex/line/server.py                  |       73 |       20 |     73% |46-48, 61-62, 67, 72, 80-82, 90-92, 94-96, 101-106 |
| vortex/line/session.py                 |      317 |       10 |     97% |376, 475, 519-521, 528, 569, 634, 669, 710 |
| vortex/line/smart\_turn\_ab.py         |      152 |        7 |     95% |115, 126, 198-200, 208, 212 |
| vortex/line/stub\_voice.py             |       44 |        7 |     84% | 34, 61-66 |
| vortex/line/submit.py                  |       60 |       22 |     63% |43, 50-68, 71, 119 |
| vortex/line/twilio.py                  |       77 |        3 |     96% |61, 153, 160 |
| vortex/line/ulaw.py                    |       48 |       11 |     77% |33-39, 52-55 |
| vortex/models.py                       |       83 |        3 |     96% |88-90, 162 |
| vortex/observability/\_\_init\_\_.py   |        3 |        0 |    100% |           |
| vortex/observability/agents.py         |       24 |        0 |    100% |           |
| vortex/observability/auth.py           |       33 |        2 |     94% |    28, 30 |
| vortex/observability/calllog.py        |       73 |       10 |     86% |48-50, 128, 135-136, 141-144 |
| vortex/observability/console.py        |      411 |       41 |     90% |36-37, 57, 67, 77, 88, 99, 158-163, 206, 229, 306, 346, 361-363, 417, 456, 485, 493-494, 498-499, 517-521, 548, 569-571, 640, 654, 731-732, 739, 828 |
| vortex/observability/demo.py           |       61 |        0 |    100% |           |
| vortex/observability/explain.py        |      323 |       65 |     80% |150, 172, 181, 183-184, 194, 196, 198, 201, 207, 227-229, 245, 252-264, 336, 378-381, 432-438, 457, 460-462, 469, 492-511, 517, 530, 587, 589-596, 609, 652 |
| vortex/observability/icons.py          |       12 |        0 |    100% |           |
| vortex/observability/insights.py       |      109 |        9 |     92% |32, 75, 78-79, 84, 95, 135, 155, 165 |
| vortex/observability/live.py           |      798 |      177 |     78% |72-78, 86, 89-90, 95-100, 108-109, 121, 132-150, 154, 177, 185-189, 195, 203, 223-225, 231, 236, 241, 244, 250-251, 296-297, 359, 363, 378-381, 391-395, 408-411, 438, 457-458, 539, 545, 570, 574-576, 580-583, 608, 617-634, 647-650, 697-705, 754-756, 825-830, 846, 857-860, 864-880, 904-905, 911, 921-922, 993-994, 997-998, 1031-1033, 1066-1079, 1092-1126, 1131, 1150-1155, 1160, 1170 |
| vortex/observability/shell.py          |      110 |        4 |     96% |133-134, 146-147 |
| vortex/observability/tracing.py        |      156 |       84 |     46% |53-63, 67-79, 85-88, 96, 107, 112-114, 140, 142, 144, 146, 148, 150-151, 157-163, 168-189, 193-198, 202, 210-214, 229-266, 275-288, 299-305, 309-311 |
| vortex/observability/view.py           |      278 |       24 |     91% |69, 71, 75, 93, 102, 113, 122, 124, 127, 156, 175-176, 185, 195, 228-229, 275-276, 305, 325-329 |
| vortex/observability/wall\_timeline.py |       79 |       68 |     14% |20-94, 106-114, 118, 127-138, 142, 150-153, 164-177 |
| vortex/rules/eligibility.py            |       99 |       15 |     85% |90, 93, 126, 144, 148, 159, 237, 291-304, 310, 313-315 |
| vortex/rules/facts.py                  |       84 |        2 |     98% |  200, 202 |
| vortex/rules/geo.py                    |      103 |       11 |     89% |239, 242-243, 255-257, 272, 278, 288-289, 330 |
| vortex/rules/tools.py                  |      161 |       17 |     89% |124, 172-173, 221-228, 338, 342, 449, 470, 509, 515 |
| vortex/rules/triage.py                 |       62 |        1 |     98% |       259 |
| vortex/settings.py                     |      214 |        2 |     99% |  365, 517 |
| vortex/tools.py                        |       93 |        7 |     92% |257, 264, 275-277, 279, 298 |
| **TOTAL**                              | **6666** |  **991** | **85%** |           |

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