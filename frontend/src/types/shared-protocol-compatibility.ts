/** Compile-time compatibility between generated wire schemas and UI projections.
 * Requests must fit the server input; every server response must fit its reader.
 * UI projections may intentionally omit unused fields. This is not runtime JSON
 * validation: Python validators and the UI's unknown-version guards still apply.
 */
import type { components } from './generated/shared-protocols';
import type { AgentInteraction, FactConfirmationInteraction, ResolveAgentInteractionResp } from './api';
import type { ConfirmInvitationCommand, ConfirmInvitationResult, InvitationHandoff,
  InvitationSubmissionReceipt } from '@/api/interviewInvitations';
import type { CareerActivity } from '@/api/careerActivity';
import type { MockClientAction, MockClientActionName, MockClientActionResolution,
  MockClientUiResult } from './clientAction';

type Wire = components['schemas'];
type Fits<From, To> = [From] extends [To] ? true : false;
type Assert<T extends true> = T;
export type SharedProtocolCompatibility = [
  Assert<Fits<ConfirmInvitationCommand, Wire['ConfirmInterviewInvitationRequestContract']>>,
  Assert<Fits<Wire['ConfirmInterviewInvitationResultResponseContract'], ConfirmInvitationResult>>,
  Assert<Fits<Wire['InterviewInvitationHandoffViewResponseContract'], InvitationHandoff>>,
  Assert<Fits<Wire['InvitationSubmissionReceiptResponseContract'], InvitationSubmissionReceipt>>,
  Assert<Fits<Wire['CareerActivityEventResponseContract'], CareerActivity>>,
  Assert<Fits<Wire['FactConfirmationRequestResponseContract'], FactConfirmationInteraction['request']>>,
  Assert<Fits<Wire['MockClientActionViewResponseContract'], MockClientAction>>,
  Assert<Fits<Wire['MockClientActionResolutionResponseResponseContract'], MockClientActionResolution>>,
  Assert<Fits<MockClientUiResult, Pick<Wire['MockClientActionResultRequestRequestContract'],
    'outcome' | 'readiness' | 'fallback_mode' | 'reason'>>>,
  Assert<Fits<Wire['AgentInteractionViewResponseContract']['kind'], AgentInteraction['kind']>>,
  Assert<Fits<AgentInteraction['kind'], Wire['AgentInteractionViewResponseContract']['kind']>>,
  Assert<Fits<Wire['MockClientActionViewResponseContract']['action'], MockClientActionName>>,
  Assert<Fits<MockClientActionName, Wire['MockClientActionViewResponseContract']['action']>>,
  Assert<Fits<Omit<Wire['AgentInteractionViewResponseContract'], 'request' | 'kind'>,
    Omit<AgentInteraction, 'request' | 'kind'>>>,
  Assert<Fits<Omit<Wire['ResolveInteractionResponseResponseContract'], 'interaction'>,
    Omit<ResolveAgentInteractionResp, 'interaction'>>>,
];

// These controls must keep failing: a broken conditional type must not silently
// turn a source-schema check into a green but empty assertion.
// @ts-expect-error a string is not a typed boolean
export type RejectBooleanDrift = Assert<Fits<'false', boolean>>;
// @ts-expect-error unknown action names cannot be treated as supported handlers
export type RejectUnknownAction = Assert<Fits<'unrecognized.effect', MockClientActionName>>;
