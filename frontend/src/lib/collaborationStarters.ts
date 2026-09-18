// Explicit user-selected starting points. These fill a draft; never auto-send.
export const collaborationStarters = {
  direction: {
    title: '找到适合我的求职方向',
    detail: '还没有具体岗位也可以。先说说经历和偏好，一起确定下一步。',
    draft: '我想梳理适合自己的求职方向。请先了解我的经历、兴趣和限制，一次只问最关键的问题。信息不足时不要替我编造经历，最后给出可比较的方向和一个具体的下一步。',
  },
  resume: {
    title: '一起改好我的简历',
    detail: '带上一份简历和目标，找出需要修改的内容，逐项确认。',
    draft: '我想改进简历。请先确认要使用哪份简历和我的目标岗位；没有资料时请让我提供。基于原文指出问题并给出修改建议，不编造经历。需要保存新版本时先让我确认。',
  },
  interview: {
    title: '准备即将到来的面试',
    detail: '告诉我们岗位和时间，把准备工作拆成能完成的步骤。',
    draft: '我想准备一场面试。请先了解岗位、面试时间和我最担心的部分，再结合已有资料确定准备重点与练习步骤。先和我确认安排，不要直接创建日程。',
  },
} as const;

export type CollaborationStarter = keyof typeof collaborationStarters;
export function readStarter(value: string | null): CollaborationStarter | null {
  return value && Object.hasOwn(collaborationStarters, value) ? value as CollaborationStarter : null;
}
