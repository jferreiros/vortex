# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/jferreiros/vortex/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                 |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------- | -------: | -------: | ------: | --------: |
| vortex/\_\_main\_\_.py               |       11 |       11 |      0% |      3-20 |
| vortex/clinic/\_\_init\_\_.py        |        9 |        1 |     89% |        24 |
| vortex/clinic/client.py              |      234 |       63 |     73% |68, 105-107, 130, 147-149, 158, 163, 349-351, 371-375, 386, 388, 393, 400-406, 409-413, 416-420, 423-427, 437-448, 461-483, 488-491, 494, 520, 548, 570, 574, 650, 654, 674 |
| vortex/clinic/fixtures.py            |       26 |        0 |    100% |           |
| vortex/contract.py                   |      386 |       28 |     93% |774-777, 781, 790, 796-797, 803, 807-813, 817, 821-823, 838, 853, 865, 871, 875, 881, 885, 889 |
| vortex/conversation/language.py      |       71 |        7 |     90% |137-138, 186-187, 195-199 |
| vortex/conversation/prompt.py        |       30 |        0 |    100% |           |
| vortex/conversation/stt\_context.py  |       41 |        3 |     93% |116, 125-126 |
| vortex/conversation/turns.py         |       34 |        0 |    100% |           |
| vortex/diary/tools.py                |      300 |       34 |     89% |248, 251, 321-322, 331-332, 335, 345-348, 406, 422, 424, 434, 496, 527, 551-552, 574-575, 629-630, 666, 673-674, 682-683, 688-689, 710, 758-759, 830 |
| vortex/identity/tools.py             |      185 |       73 |     61% |145-149, 178-184, 196-197, 210, 220-225, 242, 246-251, 253-258, 262-264, 267-272, 283, 289, 295, 320, 329-335, 362-369, 373-375, 415, 419-422, 428, 460-462, 469-477, 489-510 |
| vortex/line/pipecat\_voice.py        |      168 |       87 |     48% |68-69, 76-241, 245, 307, 430-433, 455-456, 463-483 |
| vortex/line/server.py                |       64 |       17 |     73% |44-46, 59-60, 65, 73-75, 82-84, 89-94 |
| vortex/line/session.py               |      145 |        2 |     99% |  195, 264 |
| vortex/line/stub\_voice.py           |       43 |        7 |     84% | 34, 57-62 |
| vortex/line/submit.py                |       47 |       22 |     53% |41, 48-66, 69, 89 |
| vortex/line/twilio.py                |       77 |        3 |     96% |61, 153, 160 |
| vortex/line/ulaw.py                  |       49 |       12 |     76% |22, 34-40, 53-56 |
| vortex/observability/\_\_init\_\_.py |        3 |        0 |    100% |           |
| vortex/observability/auth.py         |       33 |        6 |     82% |     26-31 |
| vortex/observability/calllog.py      |       67 |       19 |     72% |42-44, 92, 111-121, 125-128 |
| vortex/observability/demo.py         |       61 |       61 |      0% |     1-187 |
| vortex/observability/live.py         |      299 |      299 |      0% |     1-436 |
| vortex/observability/view.py         |      228 |       28 |     88% |65, 67, 69, 71, 83, 85, 88, 109, 118, 128-129, 138, 148, 165, 179-180, 194-196, 198, 223-224, 248, 267-271 |
| vortex/rules/eligibility.py          |      103 |       20 |     81% |84, 87, 114, 120, 138, 142, 153, 226, 231, 250, 261, 286, 302-315, 321, 324-326 |
| vortex/rules/facts.py                |       59 |        2 |     97% |  118, 120 |
| vortex/rules/geo.py                  |       66 |       23 |     65% |201, 206-227, 232, 237, 249 |
| vortex/rules/tools.py                |      119 |       49 |     59% |107, 110-111, 119-124, 136-143, 150-156, 201, 215-247, 279, 297-302, 321, 330-336, 339, 341, 347 |
| vortex/rules/triage.py               |       57 |        6 |     89% |63, 205-206, 217, 225, 230 |
| vortex/settings.py                   |      169 |        1 |     99% |       235 |
| vortex/tools.py                      |       51 |        9 |     82% |182, 185-187, 193-195, 197, 210 |
| **TOTAL**                            | **3235** |  **893** | **72%** |           |

6 empty files skipped.


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/jferreiros/vortex/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/jferreiros/vortex/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/jferreiros/vortex/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/jferreiros/vortex/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fjferreiros%2Fvortex%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/jferreiros/vortex/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.