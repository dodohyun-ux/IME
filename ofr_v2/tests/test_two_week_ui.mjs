import test from 'node:test'
import assert from 'node:assert/strict'
import {HISTORY_WEEKS,normalizeHistory,parseInflowCsv} from '../app/frontend/src/forecastInput.ts'
test('two-week storage migration keeps newest six cells only',()=> {
 assert.equal(HISTORY_WEEKS,2)
 const h=normalizeHistory({medyka:['1963','1818','9999'],dorohusk:[1688,1489,0],korczowa:[1327,1204,0]})
 assert.deepEqual(h,{medyka:['1963','1818'],dorohusk:['1688','1489'],korczowa:['1327','1204']})
})
test('CSV dates use reference first regardless of row order',()=> {
 const h=parseInflowCsv('week,medyka,dorohusk,korczowa\n1,1818,1489,1204\n0,"1,963",1688,1327')
 assert.deepEqual(h.medyka,['1963','1818'])
})
test('two ordered rows accepted when week column absent',()=> {
 assert.deepEqual(parseInflowCsv('Medyka,Dorohusk,Korczowa\n1,2,3\n4,5,6').korczowa,['3','6'])
})
test('CSV rejects hidden extra weeks and duplicate/missing weeks',()=> {
 for(const csv of ['week,medyka,dorohusk,korczowa\n0,1,2,3\n0,4,5,6',
 'week,medyka,dorohusk,korczowa\n0,1,2,3\n1,4,5,6\n2,7,8,9',
 'week,medyka,dorohusk,korczowa\n0,1,2,3\n2,4,5,6']) assert.throws(()=>parseInflowCsv(csv))
})
test('CSV rejects nonfinite and negative observed counts',()=> {
 for(const v of ['','NaN','Infinity','-1']) assert.throws(()=>parseInflowCsv(`medyka,dorohusk,korczowa\n${v},2,3\n4,5,6`))
})
