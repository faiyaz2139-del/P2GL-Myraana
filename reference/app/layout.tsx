import type { Metadata } from 'next';
import './globals.css';
export const metadata:Metadata={title:'Print2Go · Production Studio',description:'A clear path from artwork to finished print.'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
