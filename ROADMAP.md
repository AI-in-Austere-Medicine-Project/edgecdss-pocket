# EdgeCDSS Pocket roadmap


EdgeCDSS Pocket is a wearable, voice-driven drug dose assistant for austere medicine. This roadmap sets the order of work. Each section is a self-contained piece, so someone can pick one up without needing the rest.

The targets in the "Done when" column are working targets and may be tightened as results come in.

| # | Section | Status | Done when | How to help |
|---|---------|--------|-----------|-------------|
| 1 | **[Drug and voice system](https://github.com/AI-in-Austere-Medicine-Project/edgecdss-pocket/issues/11).** Signed doses by voice, with read-back and confirm. | In progress | Every signed drug can be asked for by voice by several different speakers, and no recording is heard as a different drug. "Yes" and "no" work at the confirm step. The EMS drug set is reviewed and signed. | Record the word list on the teach page. Try the web demo and flag anything misheard or clinically wrong. |
| 2 | **[Sound in noise](https://github.com/AI-in-Austere-Medicine-Project/edgecdss-pocket/issues/12).** Hearing and speaking clearly in vehicles, wind and with gloves on. | Not started | Word error rate is measured per condition. A microphone and earpiece are chosen from that data, and the confidence threshold is set from it. | Test microphones and headsets in real noise. Audio and signal-processing experience is welcome. |
| 3 | **[High-risk procedures](https://github.com/AI-in-Austere-Medicine-Project/edgecdss-pocket/issues/13).** Step-by-step read-out, starting with rapid sequence intubation. | Not started (RSI doses are signed) | RSI is read one step at a time with "next," "back" and "repeat," with each dose computed for the patient at its step. It has been run in scenarios. The same reader then takes other signed procedures. | Clinical review of procedure steps against their sources. Scenario testing. |
| 4 | **[Rugged box](https://github.com/AI-in-Austere-Medicine-Project/edgecdss-pocket/issues/14).** The smallest enclosure that survives field use. | Not started | Runs a full shift on battery, charges while running, speaks its battery level and shuts down cleanly. USB charging is the main supply, with an optional fold-out solar panel. | Enclosure design, 3D printing, power electronics. |
| 5 | **[Field evaluation](https://github.com/AI-in-Austere-Medicine-Project/edgecdss-pocket/issues/15).** Structured testing with clinicians. | Not started | A written protocol is run with a group of clinicians. Hearing accuracy, time to a dose compared with manual calculation, and errors caught at the read-back are measured and published. | Take part as a tester. Help with study design and analysis. |
| 6 | **[Drug sets others can edit](https://github.com/AI-in-Austere-Medicine-Project/edgecdss-pocket/issues/16).** A way for another service to enter and sign its own doses. | Not started (the drug-set mechanism exists) | Doses can be entered without a programmer. Every entry requires a source and a named signer and passes automatic checks. A second clinician reviews it. Each set has a version, and the device announces it and refuses anything unsigned. | Form and tool builders. Pharmacists and medical directors to shape the signing workflow. |
| 7 | **[The record](https://github.com/AI-in-Austere-Medicine-Project/edgecdss-pocket/issues/17).** Timers and an exportable log. | Not started (doses are logged) | Timers such as tourniquet time run and announce themselves. The log of doses and procedures can be exported for review. | Clinicians to say what a useful record contains. |
| 8 | **[Governance for sharing](https://github.com/AI-in-Austere-Medicine-Project/edgecdss-pocket/issues/18).** What is said and checked before others rely on the device. | Not started | A clear statement of responsibility for doses entered by others, a regulatory read before wider distribution, and a licence check on every component. | Regulatory, governance and legal experience. |

## Rules that apply to every section

Pocket only speaks a dose that a named clinician has signed against its source. There is no language model on the device. Every dose is read back and confirmed before it is spoken. Every fix starts with a failing test. Pocket is a research prototype, not validated for clinical use and not for patient care.

## Getting involved

Code and build notes: github.com/AI-in-Austere-Medicine-Project/edgecdss-pocket. Updates: aiamp.substack.com.
