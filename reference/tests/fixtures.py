from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image
from pathlib import Path
p=Path('tests/fixtures');p.mkdir(exist_ok=True)
pdfmetrics.registerFont(TTFont('DejaVu','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
for name,size,edge in [('valid',(270,162),False),('trim',(252,144),False),('wrong',(400,300),False),('edge',(270,162),True),('low-dpi',(270,162),False)]:
 c=canvas.Canvas(str(p/(name+'.pdf')),pagesize=size)
 for i in range(2):
  c.setFillColorRGB(.09,.17,.3);c.rect(0,0,*size,fill=1,stroke=0)
  c.setFillColorRGB(1,1,1);c.setFont('DejaVu',12)
  c.drawString(10 if edge else 32,80,'PRINT2GO' if i==0 else 'London · Ontario')
  c.setFont('DejaVu',7);c.drawString(32,55,'Artwork test fixture — not a customer job')
  if name=='low-dpi':
   im=Image.new('RGB',(60,30),(70,140,220));c.drawInlineImage(im,32,98,120,40)
  c.showPage()
 c.save()
