# Independent coarse-stage source review — findings

**STAGE_DIAGNOSTIC_SOURCE_REVIEW_FINDINGS**. Two MEDIUM defects block sourcePASS/provisioning. No app/P5/oldharness edits byreviewer. Allcurrentfourfilehashes preserved in independent-findings/reviewed-source-hashes.json before anyfix.

## STAGE-R1 — MEDIUM — endpoint thread identity mismatch

stage_latency_worker.py:26-29 uses resource.getrusage(RUSAGE_THREAD). At ingress this reads the event-loopthread. At primarysent it runs inside nativeBedrockMemorySession.send (transports.py:335-336), invoked by BedrockProvider._call_client asyncio.to_thread (bedrock_provider.py:433-436;nativeprovider runtime_clientNone). Therefore primarycounters belong toSDKworkerthread, not the approved event-loopthread. Neither endpoint retainsnativeTID; validator compares unrelatedcounters asmonotonic andmay falseFAILafterworker completion or accept meaninglessdelta ifnumericallyincreasing. ProcessCPUtime remains process-global and isnot affected by this specificmislabel.

Deterministicpureprobe patchesgetrusage to returnloop100/30 switches andotherthread2/1; callsactualendpoint inloop and manuallyjoinedplainthread. It provesdecliningunrelatedcounter values withzeroSDK/API/serviceoperations. Parentfullnative tests only assertedfunctionalrows ratherthan thisendpointtargetidentity, so289passingtests do notdisprovefinding.

Minimalfix: captureingress eventloopnativeTID, readcountersforthatthread atbothboundaries (e.g. existingLinux/proc/self/task/TID/status),retain reader/targetTIDs,failclosed onmissing/changedtarget. No sampler,queuedloopcallback, RUSAGE_SELF substitution, provider/workerthreadbehaviorchange or waitingtimeinference. Checkendpointdata afterquiescence before markingPASS/admittingnextrequest. BothON/OFFsameendpointpolicy. Native transport test must proveboundary executesworkerthread buttarget remainsloopthread, plusgone/wrongtarget/readfailure cases.

## STAGE-R2 — MEDIUM — observer wall failure prevents functional call

stage_latency_worker.py:48 and ingressfirstwalltimestamp call time.monotonic_ns directly outside read_endpoint'sguard. Ifclockreadraises, capture.sent'soriginal isnevercalled; ingressexceptioncanlikewisepreventASGIexecution. This altersfunctionalrequest/providererror/retry behavior instead of only invalidatingdiagnostic. Existingclock-failure testinjectsStageObserver.wall, not newworkerendpointwallcall, so misses it.

Pureprobe AST-extractstheactualsentcallback, injectsmonotonic_nsRuntimeError and countsoriginalcalls:exceptionescapes andcount0. NoHTTP/ASGI/provider/serviceexecution. Minimalfix a first-operation safewallread thatrecords invalidobservation and continuesoriginalexactlyonce; preserveexceptions/returnsofactualoriginal, avoidformatting/subtractionofmissingdata. Validatewall/processCPU/counters/order/correlation immediatelyafterquiescence beforestatusPASS/newadmission, notonlyend-of-workercontrollervalidation. Addpureandnative-control tests for clockthrow/backwards/counterreset showingfunctionalresultunchanged,failedrowpreserved andnomoreadmission. No globalclockmonkeypatch inproduct.

## Other scoped checks and actual verification

Inspected approvedproposal/sourceauthorization,allthree modules/tests, actualstagealiases/decorators/SQLAlchemyenginekeys andBedrockthreadhandoff. ReviewedboundedContextVarparentstack, intervalclosure/overlapclipping, existingWaitObserverreuse, restorefinally,fullC1botharms/nativehashproof,schema/preparation/marker/source/configguards and fixed360population. NoadditionalconfirmedB/H/M atthisstage; finalreviewneededafterremediation,not a broadfuturesafetyclaim.

Reviewer boundedpureP2 tests:30PASS/6nativecasesdeselected on earlierreviewedversion, beforeparentaddedON-controls. Parentthenfroze currentversion:44focused/289regressions P2imagePASS; parentattributed XML,notreviewerDockerexecution. Twoindependentpurecounterexamples inindependent-findings/probes.py PASS under timeout15s/unshare-rn/env-i/P2,0services. Usesplainboundedthread/join, nothostasyncioexecutor. NoDB/SQL/Docker/API/providers/network/newexperiment byreviewer;no technicalfilechanges. Sourcechanges duringinitialreview are noted; finalhashsnapshot bound below reflects frozenpostONtestversion, not earlier30-testversion.

Do notcreatePASSsource-review receipt orprovision beforefix/re-review. Preserveauthorization/proposal/source/errorhistory;fixonlynewdiagnosticfiles/tests. HistoricalAA/G6FAIL/paidblock unchanged; no360requestexecution or latencycausality/gateacceptance bythisreview.
