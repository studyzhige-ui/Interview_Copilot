from pathlib import Path
import re
p=Path(__file__).parent
source=Path('C:/Users/Alice/.codex/visualizations/2026/09/10/01a0891e-52af-78a0-89a1-d82b8646c80f/today-garden.html').read_text(encoding='utf-8')
source=source.replace('</style>',p.joinpath('refine.css').read_text(encoding='utf-8')+'\n</style>',1)
source=source.replace('renderCalendar();renderAgenda();if(globalThis.Tweak)',p.joinpath('refine.js').read_text(encoding='utf-8')+'\nrenderCalendar();renderAgenda();if(globalThis.Tweak)')
source=source.replace('</style>',p.joinpath('orbit.css').read_text(encoding='utf-8')+'\n</style>',1)
source=source.replace('renderCalendar();renderAgenda();if(globalThis.Tweak)',p.joinpath('orbit.js').read_text(encoding='utf-8')+'\nrenderCalendar();renderAgenda();if(globalThis.Tweak)')
p.joinpath('today-orbit.html').write_text(source,encoding='utf-8')
p.joinpath('syntax-check.js').write_text(re.search(r'<script>([\s\S]*?)</script>',source)[1],encoding='utf-8')
print('Built',p.joinpath('today-orbit.html'))
