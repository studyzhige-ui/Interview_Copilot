import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { InterviewRecordDetail, InterviewRecordListItem } from '@/types/api';
import { ReviewPage } from '@/pages/review/ReviewPage';
import { getInterviewRecord, listInterviewRecords } from '@/api/interview';
vi.mock('@/api/interview',()=>({getInterviewRecord:vi.fn(),listInterviewRecords:vi.fn(),cancelAnalyze:vi.fn(),reanalyzeRecord:vi.fn()}));
vi.mock('@/api/mock',()=>({retryMockReview:vi.fn()}));
vi.mock('@/pages/review/SessionList',()=>({SessionList:({onSelect,onChanged}:{onSelect:(id:string)=>void;onChanged:()=>void})=><><button onClick={()=>onSelect('two')}>选择第二条记录</button><button onClick={onChanged}>刷新侧栏</button></>}));
vi.mock('@/pages/review/QAPanel',()=>({QAPanel:({detail,loading}:{detail:InterviewRecordDetail|null;loading?:boolean})=><div>{loading?'读取中':detail?`报告:${detail.id}`:'无报告'}</div>}));
vi.mock('@/pages/review/chat/ChatPanel',()=>({ChatPanel:({interviewId}:{interviewId:string})=><div>复盘对象:{interviewId}</div>}));
vi.mock('@/pages/review/UploadCards',()=>({UploadCards:()=>null,applyDraftMetadata:vi.fn()}));
vi.mock('@/pages/review/AnalysisRunner',()=>({AnalysisRunner:()=>null}));
afterEach(cleanup);
function detail(id:string):InterviewRecordDetail { return { id, title:id, source:'upload', status:'completed', created_at:'2026-09-30', tag:null, analyzed_qa_count:0, category:null, audio_file_asset_id:null, resume_id:null, resume_file_asset_id:null, resume_source:null, jd_file_asset_id:null, transcript:'Synthetic transcript', transcript_segments:null, analysis:null, qa:[], error_message:null, updated_at:'2026-09-30', completed_at:null }; }
beforeEach(()=>{vi.clearAllMocks();vi.mocked(listInterviewRecords).mockResolvedValue(['one','two'].map(id=>detail(id) as InterviewRecordListItem));vi.mocked(getInterviewRecord).mockImplementation(async id=>detail(id))});
function Nav(){const navigate=useNavigate();return <button onClick={()=>navigate('/review?id=one')}>导航到第一条</button>}
function show(path:string){render(<MemoryRouter initialEntries={[path]}><QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><Nav/><ReviewPage/></QueryClientProvider></MemoryRouter>)}
it('a direct history link must load its record even outside the first list page',async()=>{
 show('/review?id=older-than-first-50');
 await waitFor(()=>expect(getInterviewRecord).toHaveBeenCalled());
 expect(vi.mocked(getInterviewRecord).mock.calls.at(-1)?.[0]).toBe('older-than-first-50');
});
it('same-page navigation must change the review object after a manual selection',async()=>{
 show('/review?id=one');
 expect(await screen.findByText('复盘对象:one')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'选择第二条记录'}));
 expect(await screen.findByText('复盘对象:two')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'导航到第一条'}));
 await waitFor(()=>expect(screen.getByText('复盘对象:one')).toBeInTheDocument());
});

it('shows an inaccessible target with retry rather than another record or a composer',async()=>{
 vi.mocked(getInterviewRecord).mockRejectedValueOnce(new Error('not found')).mockImplementation(async id=>detail(id));
 show('/review?id=missing');
 expect(await screen.findByRole('alert')).toHaveTextContent('面试记录暂不可用');
 expect(screen.queryByText('复盘对象:one')).not.toBeInTheDocument();
 expect(screen.queryByText('复盘对象:missing')).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'重新加载这条记录'}));
 expect(await screen.findByText('复盘对象:missing')).toBeInTheDocument();
});
it('refreshing a list page does not declare an older record deleted',async()=>{
 show('/review?id=old');
 expect(await screen.findByText('复盘对象:old')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'刷新侧栏'}));
 await waitFor(()=>expect(listInterviewRecords).toHaveBeenCalledTimes(2));
 expect(await screen.findByText('复盘对象:old')).toBeInTheDocument();
 expect(vi.mocked(getInterviewRecord).mock.calls.at(-1)?.[0]).toBe('old');
});
it('ignores a late detail response after the user selects a newer record',async()=>{
 let resolve!:(value:InterviewRecordDetail)=>void;
 vi.mocked(getInterviewRecord).mockImplementation(id=>id==='one'?new Promise(done=>{resolve=done}):Promise.resolve(detail(id)));
 show('/review?id=one');
 await waitFor(()=>expect(getInterviewRecord).toHaveBeenCalled());
 fireEvent.click(screen.getByRole('button',{name:'选择第二条记录'}));
 expect(await screen.findByText('复盘对象:two')).toBeInTheDocument();
 await act(async()=>resolve(detail('one')));
 expect(screen.getByText('复盘对象:two')).toBeInTheDocument();
 expect(screen.queryByText('报告:one')).not.toBeInTheDocument();
});
