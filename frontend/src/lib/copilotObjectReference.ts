import type { ProductObjectKind, ProductObjectReference } from '@/types/api';

const PRODUCT_OBJECT_KINDS = new Set<ProductObjectKind>([
  'career_profile',
  'career_profile_direction',
  'job_opportunity',
  'next_action',
  'artifact',
  'interview_record',
]);

const KIND_LABELS: Record<ProductObjectKind, string> = {
  career_profile: '个人详情与求职方向',
  career_profile_direction: '求职方向',
  job_opportunity: '岗位机会',
  next_action: '下一步行动',
  artifact: '求职材料',
  interview_record: '面试记录',
};

export function productObjectReferenceLabel(reference: ProductObjectReference): string {
  return reference.label?.trim() || `${KIND_LABELS[reference.kind]} · ${reference.object_id}`;
}

export function copilotObjectHandoffHref(
  kind: ProductObjectKind,
  objectId: string,
  label: string,
): string {
  const params = new URLSearchParams({
    object_kind: kind,
    object_id: objectId,
    object_label: label.slice(0, 240),
  });
  return `/general-chat?${params.toString()}`;
}

export function readCopilotObjectHandoff(
  params: URLSearchParams,
): ProductObjectReference | null {
  const kind = params.get('object_kind') as ProductObjectKind | null;
  const objectId = params.get('object_id')?.trim() ?? '';
  if (!kind || !PRODUCT_OBJECT_KINDS.has(kind) || !objectId || objectId.length > 128) {
    return null;
  }
  const rawLabel = params.get('object_label')?.trim() ?? '';
  return {
    kind,
    object_id: objectId,
    ...(rawLabel ? { label: rawLabel.slice(0, 240) } : {}),
  };
}

export function clearCopilotObjectHandoff(params: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(params);
  next.delete('object_kind');
  next.delete('object_id');
  next.delete('object_label');
  return next;
}
