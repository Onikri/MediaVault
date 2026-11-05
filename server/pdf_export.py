"""Stream a PDF one decoded page at a time, without retaining image sequences."""
import io
from PIL import Image
from source_parser import SourceError


def write_pdf(paths, output, budget):
    offsets = [0] * (3 + len(paths) * 3)
    with open(output, 'wb') as target:
        target.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
        def obj(identity, body):
            offsets[identity] = target.tell()
            target.write(f'{identity} 0 obj\n'.encode() + body + b'\nendobj\n')
        obj(1, b'<< /Type /Catalog /Pages 2 0 R >>')
        kids = ' '.join(f'{3+i*3} 0 R' for i in range(len(paths)))
        obj(2, f'<< /Type /Pages /Count {len(paths)} /Kids [{kids}] >>'.encode())
        for index, path in enumerate(paths):
            budget.check()
            with Image.open(path) as source, source.convert('RGB') as image:
                width, height = image.size
                buffer = io.BytesIO()
                image.save(buffer, 'JPEG', quality=95)
            jpeg = buffer.getvalue()
            page = 3 + index * 3
            obj(page, f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width/2:g} {height/2:g}] /Resources << /XObject << /Im {page+1} 0 R >> >> /Contents {page+2} 0 R >>'.encode())
            obj(page+1, f'<< /Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg)} >>\nstream\n'.encode() + jpeg + b'\nendstream')
            content = f'q {width/2:g} 0 0 {height/2:g} 0 0 cm /Im Do Q'.encode()
            obj(page+2, f'<< /Length {len(content)} >>\nstream\n'.encode()+content+b'\nendstream')
            if target.tell() > budget.maximum:
                raise SourceError('PDF превышает лимит скачивания.')
        xref = target.tell()
        target.write(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
        for offset in offsets[1:]:
            target.write(f'{offset:010d} 00000 n \n'.encode())
        target.write(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
