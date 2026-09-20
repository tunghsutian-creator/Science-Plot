import {readFile,writeFile,mkdir,readdir} from 'node:fs/promises'
const packages=['react','react-dom','scheduler','clsx','tailwind-merge','tailwindcss']
const sections=[]
for(const name of packages){
 const pkg=JSON.parse(await readFile(new URL(`../node_modules/${name}/package.json`,import.meta.url),'utf8'))
 const directory=new URL(`../node_modules/${name}/`,import.meta.url)
 const filename=(await readdir(directory)).find(file=>/^licen[sc]e(\.|$)/i.test(file))
 if(!filename)throw new Error(`Missing license for ${name}`)
 const notice=await readFile(new URL(filename,directory),'utf8')
 sections.push(`${name} ${pkg.version}\n${pkg.repository?.url??pkg.repository??''}\n\n${notice.trim()}`)
}
await mkdir(new URL('../public',import.meta.url),{recursive:true})
await writeFile(new URL('../public/dependency-LICENSES.txt',import.meta.url),sections.join('\n\n'+'='.repeat(72)+'\n\n')+'\n')
const source=await readFile(new URL('../THIRD_PARTY.md',import.meta.url),'utf8')
const packaged=source.replaceAll('(public/tavotto-LICENSE.txt)','(tavotto-LICENSE.txt)')
await writeFile(new URL('../public/THIRD_PARTY.md',import.meta.url),packaged+'\nRuntime dependency licenses and exact installed versions: [dependency-LICENSES.txt](dependency-LICENSES.txt).\n')
