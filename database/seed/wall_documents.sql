-- Vortex wall-document seed: the two editable documents the Clinic View's
-- Pathways and Patterns editors open on.
--
--   uv run python database/scripts/load_seed.py --only wall_documents.sql
--
-- These used to ship inside the React bundle as vortex/wall/src/data/
-- pathways.json and patterns.json, which meant an editor that saved to the
-- server still reloaded the bundled copy. They are data the clinic edits, so
-- they live in Postgres now and the SPA only ever reads GET /api/wall/
-- pathways and /patterns.
--
-- Not seeded here, and deliberately still in the bundle: shapeTypes.json and
-- patternShapes.json. Those are the editors' tray vocabulary — families,
-- types, emoji, labels, gap units — not clinic data, and nothing in the
-- product writes them.
--
-- Data only. The table comes from database/supabase/migrations/. Re-running
-- is safe: kind is the primary key and a row already there is kept, so a
-- clinic that has edited its pathways never has them reset by a seed load.

insert into public.wall_documents (kind, body, updated_at) values
    ('pathways', $doc${
  "pathways": [
    {
      "id": "annual-physical-exam",
      "name": "Annual Physical Exam",
      "description": "Yearly checkup: schedule, pre-visit intake, fasting prep, exam, results, and an automatic call to book next year's exam.",
      "nodes": [
        {
          "id": "annual-physical-exam-n1",
          "shape": {
            "family": "entry"
          },
          "when": null,
          "description": "Client requests checkup"
        },
        {
          "id": "annual-physical-exam-n2",
          "shape": {
            "family": "message",
            "type": "form"
          },
          "when": {
            "kind": "asap"
          },
          "description": "Medical history questionnaire"
        },
        {
          "id": "annual-physical-exam-n3",
          "shape": {
            "family": "message",
            "type": "SMS"
          },
          "when": {
            "kind": "proactive",
            "amount": 2,
            "unit": "days",
            "direction": "before",
            "referenceNode": 4
          },
          "description": "Fasting instructions"
        },
        {
          "id": "annual-physical-exam-n4",
          "shape": {
            "family": "visit",
            "type": "standard consultation"
          },
          "when": {
            "kind": "when_scheduled"
          },
          "description": "Physical exam & blood draw"
        },
        {
          "id": "annual-physical-exam-n5",
          "shape": {
            "family": "message",
            "type": "results"
          },
          "when": {
            "kind": "asap"
          },
          "description": "Lab results published"
        },
        {
          "id": "annual-physical-exam-n6",
          "shape": {
            "family": "call",
            "type": "appointment suggestion"
          },
          "when": {
            "kind": "proactive",
            "amount": 340,
            "unit": "days",
            "direction": "after",
            "referenceNode": 4
          },
          "description": "Book next year's exam"
        }
      ]
    },
    {
      "id": "allergy-panel-workup",
      "name": "Allergy Panel Workup",
      "description": "Allergy testing intake with a pre-test washout reminder, the panel visit, results, and a follow-up consultation call.",
      "nodes": [
        {
          "id": "allergy-panel-workup-n1",
          "shape": {
            "family": "entry"
          },
          "when": null,
          "description": "Requests allergy testing"
        },
        {
          "id": "allergy-panel-workup-n2",
          "shape": {
            "family": "message",
            "type": "form"
          },
          "when": {
            "kind": "asap"
          },
          "description": "Symptoms & medication form"
        },
        {
          "id": "allergy-panel-workup-n3",
          "shape": {
            "family": "message",
            "type": "SMS"
          },
          "when": {
            "kind": "proactive",
            "amount": 5,
            "unit": "days",
            "direction": "before",
            "referenceNode": 4
          },
          "description": "Antihistamine washout reminder"
        },
        {
          "id": "allergy-panel-workup-n4",
          "shape": {
            "family": "visit",
            "type": "diagnostic test / lab"
          },
          "when": {
            "kind": "when_scheduled"
          },
          "description": "Skin-prick panel testing"
        },
        {
          "id": "allergy-panel-workup-n5",
          "shape": {
            "family": "message",
            "type": "results"
          },
          "when": {
            "kind": "asap"
          },
          "description": "Allergy results published"
        },
        {
          "id": "allergy-panel-workup-n6",
          "shape": {
            "family": "call",
            "type": "appointment suggestion"
          },
          "when": {
            "kind": "proactive",
            "amount": 14,
            "unit": "days",
            "direction": "after",
            "referenceNode": 4
          },
          "description": "Schedule allergist follow-up"
        }
      ]
    },
    {
      "id": "new-patient-onboarding",
      "name": "New Patient Onboarding",
      "description": "Registration, intake paperwork, the first visit, and a 6-month check-in call.",
      "nodes": [
        {
          "id": "new-patient-onboarding-n1",
          "shape": {
            "family": "entry"
          },
          "when": null,
          "description": "New patient registration call"
        },
        {
          "id": "new-patient-onboarding-n2",
          "shape": {
            "family": "message",
            "type": "form"
          },
          "when": {
            "kind": "asap"
          },
          "description": "ID, insurance & history form"
        },
        {
          "id": "new-patient-onboarding-n3",
          "shape": {
            "family": "message",
            "type": "SMS"
          },
          "when": {
            "kind": "proactive",
            "amount": 1,
            "unit": "days",
            "direction": "before",
            "referenceNode": 4
          },
          "description": "Reminder: address & documents"
        },
        {
          "id": "new-patient-onboarding-n4",
          "shape": {
            "family": "visit",
            "type": "standard consultation"
          },
          "when": {
            "kind": "when_scheduled"
          },
          "description": "Initial consultation visit"
        },
        {
          "id": "new-patient-onboarding-n5",
          "shape": {
            "family": "message",
            "type": "form"
          },
          "when": {
            "kind": "asap"
          },
          "description": "Post-visit satisfaction survey"
        },
        {
          "id": "new-patient-onboarding-n6",
          "shape": {
            "family": "call",
            "type": "appointment suggestion"
          },
          "when": {
            "kind": "proactive",
            "amount": 180,
            "unit": "days",
            "direction": "after",
            "referenceNode": 4
          },
          "description": "Schedule 6-month check-in"
        }
      ]
    },
    {
      "id": "no-show-recovery-rebooking",
      "name": "No-Show Recovery & Rebooking",
      "description": "Detects a missed appointment and automatically offers, confirms and reminds about a rebooked visit.",
      "nodes": [
        {
          "id": "no-show-recovery-rebooking-n1",
          "shape": {
            "family": "entry"
          },
          "when": null,
          "description": "No-show detected"
        },
        {
          "id": "no-show-recovery-rebooking-n2",
          "shape": {
            "family": "message",
            "type": "SMS"
          },
          "when": {
            "kind": "asap"
          },
          "description": "Missed-appointment rebook link"
        },
        {
          "id": "no-show-recovery-rebooking-n3",
          "shape": {
            "family": "call",
            "type": "rebooking offer"
          },
          "when": {
            "kind": "proactive",
            "amount": 3,
            "unit": "days",
            "direction": "after",
            "referenceNode": 1
          },
          "description": "Call offering to rebook"
        },
        {
          "id": "no-show-recovery-rebooking-n4",
          "shape": {
            "family": "visit",
            "type": "standard consultation"
          },
          "when": {
            "kind": "when_scheduled"
          },
          "description": "Rebooked visit"
        },
        {
          "id": "no-show-recovery-rebooking-n5",
          "shape": {
            "family": "message",
            "type": "SMS"
          },
          "when": {
            "kind": "proactive",
            "amount": 1,
            "unit": "days",
            "direction": "before",
            "referenceNode": 4
          },
          "description": "Rebooked visit reminder"
        }
      ]
    }
  ]
}$doc$::jsonb, '2026-09-20T00:00:00Z'),
    ('patterns', $doc${
  "dataSources": {
    "visits": "GET /api/v1/patients/{patient_id}/appointments?when=all — past visits; appointment_type_id → specialty via GET /api/v1/appointment-types.",
    "callOutcomes": "GET /api/v1/submissions?limit=50, filtered by patient_id — only book/reschedule/cancel carry patient_id today.",
    "referrals": "patients.json[].referrals[] — open referral specialties on the directory record.",
    "needsCallLog": "Future patient-indexed log of every call (including no_action/escalate). Patterns no-availability-unrecovered and repeat-callers-unresolved depend on it."
  },
  "specialtyRecallDays": {
    "cardiology": 365,
    "dermatology": 180,
    "default": 365
  },
  "asOf": "2026-09-19",
  "patterns": [
    {
      "id": "first-visit-then-gap",
      "name": "First visit, then gap",
      "enabled": true,
      "buildableToday": true,
      "match": {
        "perSpecialty": true,
        "visitCount": {
          "eq": 1
        },
        "noBookSinceLastVisit": true,
        "daysSinceLastVisit": {
          "gtSpecialtyRecall": true
        }
      },
      "nodes": [
        {
          "id": "n1",
          "shape": {
            "family": "visit",
            "type": "any visit"
          },
          "description": "Exactly one visit in <specialty>"
        },
        {
          "id": "n2",
          "shape": {
            "family": "condition",
            "type": "time gap"
          },
          "description": "Days since that visit > specialty recall interval"
        },
        {
          "id": "n3",
          "shape": {
            "family": "condition",
            "type": "no follow-up"
          },
          "description": "No book in <specialty> since that visit"
        }
      ],
      "suggestionNode": {
        "shape": {
          "family": "call",
          "subfamily": "outgoing",
          "type": "appointment suggestion"
        },
        "description": "Offer to schedule the next visit in <specialty>.",
        "chainLabel": "Follow-up call"
      }
    },
    {
      "id": "broken-cadence",
      "name": "Broken cadence",
      "enabled": true,
      "buildableToday": true,
      "match": {
        "perSpecialty": true,
        "visitCount": {
          "min": 2
        },
        "visitsFormRegularCadence": true,
        "cadenceOverdue": true,
        "noBookSinceLastVisit": true
      },
      "nodes": [
        {
          "id": "n1",
          "shape": {
            "family": "visit",
            "type": "any visit"
          },
          "description": "1st visit in <specialty>"
        },
        {
          "id": "n2",
          "shape": {
            "family": "visit",
            "type": "any visit"
          },
          "description": "2nd+ visit at a regular interval"
        },
        {
          "id": "n3",
          "shape": {
            "family": "condition",
            "type": "time gap"
          },
          "description": "Next visit by that cadence is overdue"
        },
        {
          "id": "n4",
          "shape": {
            "family": "condition",
            "type": "no follow-up"
          },
          "description": "No book in <specialty> since last visit"
        }
      ],
      "suggestionNode": {
        "shape": {
          "family": "call",
          "subfamily": "outgoing",
          "type": "appointment suggestion"
        },
        "description": "Offer to keep the cadence and book the next visit in <specialty>.",
        "chainLabel": "Cadence call"
      }
    },
    {
      "id": "unfulfilled-referral",
      "name": "Unfulfilled referral",
      "enabled": true,
      "buildableToday": true,
      "match": {
        "perSpecialty": true,
        "hasOpenReferral": true,
        "visitCount": {
          "eq": 0
        },
        "noBookEver": true
      },
      "nodes": [
        {
          "id": "n1",
          "shape": {
            "family": "condition",
            "type": "open referral"
          },
          "description": "Open referral to <specialty>"
        },
        {
          "id": "n2",
          "shape": {
            "family": "condition",
            "type": "no follow-up"
          },
          "description": "No book and no visit in <specialty>"
        }
      ],
      "suggestionNode": {
        "shape": {
          "family": "call",
          "subfamily": "outgoing",
          "type": "appointment suggestion"
        },
        "description": "Ask whether they'd like to book the <specialty> they were referred to.",
        "chainLabel": "Referral call"
      }
    },
    {
      "id": "cancelled-without-replacement",
      "name": "Cancelled without replacement",
      "enabled": true,
      "buildableToday": true,
      "match": {
        "perSpecialty": true,
        "hasCall": {
          "type": "cancellation",
          "subfamily": "incoming"
        },
        "noBookSince": "last_cancellation"
      },
      "nodes": [
        {
          "id": "n1",
          "shape": {
            "family": "call",
            "subfamily": "incoming",
            "type": "cancellation"
          },
          "description": "Cancel in <specialty>"
        },
        {
          "id": "n2",
          "shape": {
            "family": "condition",
            "type": "no follow-up"
          },
          "description": "No book in <specialty> since that cancel"
        }
      ],
      "suggestionNode": {
        "shape": {
          "family": "call",
          "subfamily": "outgoing",
          "type": "rebooking offer"
        },
        "description": "Offer to rebook the cancelled visit in <specialty>.",
        "chainLabel": "Rebook call"
      }
    },
    {
      "id": "no-availability-unrecovered",
      "name": "No-availability, unrecovered",
      "enabled": true,
      "buildableToday": false,
      "needsCallLog": true,
      "match": {
        "perSpecialty": true,
        "hasCall": {
          "type": "no availability",
          "subfamily": "incoming"
        },
        "noCallOrVisitSince": {
          "ref": "last_no_availability",
          "withinDays": 14
        }
      },
      "nodes": [
        {
          "id": "n1",
          "shape": {
            "family": "call",
            "subfamily": "incoming",
            "type": "no availability"
          },
          "description": "Call ended no_action / no_availability in <specialty>"
        },
        {
          "id": "n2",
          "shape": {
            "family": "condition",
            "type": "no follow-up"
          },
          "description": "No call or visit in <specialty> within 14 days since"
        }
      ],
      "suggestionNode": {
        "shape": {
          "family": "call",
          "subfamily": "outgoing",
          "type": "waitlist alert"
        },
        "description": "Offer the first newly-open slot in <specialty> (waitlist-style).",
        "chainLabel": "Waitlist call"
      }
    },
    {
      "id": "repeat-callers-unresolved",
      "name": "Repeat callers, unresolved",
      "enabled": true,
      "buildableToday": false,
      "needsCallLog": true,
      "match": {
        "perSpecialty": false,
        "incomingCallCount": {
          "min": 2,
          "withinDays": 14
        },
        "noSuccessfulBookInWindow": true
      },
      "nodes": [
        {
          "id": "n1",
          "shape": {
            "family": "call",
            "subfamily": "incoming",
            "type": "general"
          },
          "description": "Incoming call"
        },
        {
          "id": "n2",
          "shape": {
            "family": "call",
            "subfamily": "incoming",
            "type": "general"
          },
          "description": "Another incoming call within 14 days"
        },
        {
          "id": "n3",
          "shape": {
            "family": "condition",
            "type": "no follow-up"
          },
          "description": "No successful book in that window"
        }
      ],
      "suggestionNode": {
        "shape": {
          "family": "call",
          "subfamily": "outgoing",
          "type": "rebooking offer"
        },
        "description": "Offer an alternative (provider/site/time) or escalate for prioritized handling.",
        "chainLabel": "Alternative call"
      }
    }
  ]
}$doc$::jsonb, '2026-09-20T00:00:00Z')
on conflict (kind) do nothing;
