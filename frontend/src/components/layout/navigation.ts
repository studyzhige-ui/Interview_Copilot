export const workspaces = [
  { label: '今天', to: '/today', paths: ['/today'], tabs: [] },
  { label: '求职', to: '/career-process', paths: ['/career-process', '/career-insights'], tabs: [
    { label: '岗位与进展', to: '/career-process' }, { label: '行动与决策', to: '/career-insights' },
  ] },
  { label: '面试', to: '/interviews', paths: ['/interviews', '/mock', '/review', '/analytics'], tabs: [
    { label: '面试准备', to: '/interviews' }, { label: '模拟面试', to: '/mock' }, { label: '面试复盘', to: '/review' }, { label: '能力成长', to: '/analytics' },
  ] },
  { label: '资料', to: '/career-profile', paths: ['/career-profile', '/artifacts', '/library'], tabs: [
    { label: '个人档案', to: '/career-profile' }, { label: '求职材料', to: '/artifacts' }, { label: '资料库', to: '/library' },
  ] },
  { label: '协作记录', to: '/history', paths: ['/history', '/activity', '/persistent-tasks'], tabs: [
    { label: '活动记录', to: '/activity' }, { label: '历史记录', to: '/history' }, { label: '持续任务', to: '/persistent-tasks' },
  ] },
  { label: '设置', to: '/settings/personalization', paths: ['/settings', '/models', '/plugins', '/capabilities', '/me'], tabs: [
    { label: '协作偏好', to: '/settings/personalization' }, { label: '回答模型', to: '/models' },
    { label: '插件与连接', to: '/plugins' }, { label: '账户', to: '/me' },
  ] },
];

export function pathMatches(pathname: string, path: string) {
  return pathname === path || pathname.startsWith(`${path}/`);
}

export function workspaceFor(pathname: string) {
  return workspaces.find((area) => area.paths.some((path) => pathMatches(pathname, path)));
}
