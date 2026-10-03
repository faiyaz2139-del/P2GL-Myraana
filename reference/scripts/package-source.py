from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
root=Path(__file__).resolve().parent.parent
output=root/'public/setup/Print2Go_Production_Studio_Source.zip'
folders=['app','lib','db','drizzle','build','scripts','components','hooks','vendor','docs','tests']
files=['package.json','pnpm-lock.yaml','tsconfig.json','vite.config.ts','drizzle.config.ts','postcss.config.mjs','next.config.ts','cloudflare-env.d.ts','eslint.config.mjs','components.json','README.md','.gitignore','.npmrc','.openai/hosting.json','public/pdf.worker.mjs','public/favicon.svg','public/setup/print2go-connector.py','public/setup/Business_Card_Recipe.json']
with ZipFile(output,'w',ZIP_DEFLATED) as z:
 for folder in folders:
  for p in (root/folder).rglob('*'):
   if p.is_file() and '__pycache__' not in p.parts:z.write(p,p.relative_to(root))
 for f in files:
  p=root/f
  if p.exists():z.write(p,f)
print('Source archive created:',output)
