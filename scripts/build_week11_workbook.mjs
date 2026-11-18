// Bundled @oai/artifact-tool only. Runtime dependency bridge is not a repo dependency.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const require = createRequire(path.resolve('.local-week11-workbook/loader.cjs'));
const { Workbook, SpreadsheetFile } = await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const [input, output, previewDir] = process.argv.slice(2);
if (!input || !output || !previewDir) throw new Error('input JSON, output XLSX, preview directory required');
const payload = JSON.parse(await fs.readFile(input, 'utf8'));
const f = payload.findings;
const wb = Workbook.create();
const navy = '#17324D', blue = '#E8F0F8', red = '#9C2737', gray = '#516174';
const dashboard = wb.worksheets.add('Dashboard');
const actual = wb.worksheets.add('Actual v3 picks');
const index = wb.worksheets.add('Guide');
const col = n => { let out=''; for(n++;n;n=Math.floor((n-1)/26)) out=String.fromCharCode(65+(n-1)%26)+out;return out; };
function base(sheet, rows, cols) {
  sheet.showGridLines=false;
  sheet.getRangeByIndexes(0,0,rows,cols).format.font={name:'Arial',size:10,color:'#182B3C'};
  sheet.getRangeByIndexes(0,0,rows,cols).format.rowHeight=24;
  sheet.getRangeByIndexes(0,0,rows,cols).format.verticalAlignment='center';
  sheet.tabColor=navy;
}
function head(sheet,range){sheet.getRange(range).format={fill:navy,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,horizontalAlignment:'center',verticalAlignment:'center'};}
function value(key,v){
  if(v===undefined||v===null||v==='')return null;
  if(typeof v!=='string')return typeof v==='object'?JSON.stringify(v):v;
  if(/(^|_)(id|sha256|source|path|pdf|timestamp|date|time|code|record)(_|$)/i.test(key)||key.endsWith('_exact'))return v;
  if(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(v)&&Number.isFinite(Number(v)))return Number(v);
  if(v==='True'||v==='False')return v==='True';
  return v;
}
const skipNested=new Set(['process','observed_teams','observed_passers','reliability']);
const tabs=[
 ['All 621 games','season_game_reconciliation.csv'],['PDF export source','source_exports.csv'],
 ['External records','external_week11_records_not_graded.csv'],['Recommendation matches','submission_recommendation_differences.csv'],
 ['Historical lines','historical_line_reconciliation.csv'],['Kickoff changes','week11_export_kickoff_differences.csv'],
 ['W11 ATS','week11_ats_audit.csv'],['W11 totals','week11_totals_audit.csv'],
 ['W11 cohort results','cohort_results.csv'],['W11 cohort members','cohort_membership.csv'],['Cohort overlap','cohort_overlap.csv'],
 ['Season recommendations','season_recommendation_ledger.csv'],['Season cohort results','season_recommendation_performance.csv'],
 ['Confidence calibration','confidence_calibration.csv'],['Market baseline','forecast_vs_market.csv'],
 ['Segment diagnostics','segment_diagnostics.csv'],['Comparable progression','cumulative_performance.csv'],
 ['Cumulative rankings','cumulative_rank_performance.csv'],['Early coverage','earlier_week_qualified_records.csv'],
 ['Frozen forecast ledger','cumulative_grade_ledger.csv'],['Context confidence','human_confidence_ledger.csv'],
 ['Edge discrimination','ranking_discrimination.csv'],['Market observations','clv_observations.csv'],
 ['Hooks and backdoors','hook_backdoor_audit.csv'],['Game process','game_process.csv'],['Team process','team_process.csv'],
 ['Observed passers','observed_passers.csv'],['Nonoffensive scoring','nonoffensive_scoring.csv'],
 ['Pregame vs observed','pregame_context_comparison.csv'],
 ['Logic failures','logic_failure_priority.csv'],['Frozen methods','frozen_research_metrics.csv'],
 ['Frozen research Top5','frozen_research_top5.csv'],['Research membership','frozen_research_membership.csv'],
 ['Research predictions','frozen_research_all_grades.csv'],['Research reliability','frozen_research_reliability.csv'],
 ['Drive forecasts','frozen_drive_forecasts.csv'],['Drive corrections','drive_quarantine_adjudication.csv'],
 ['V29 chronological folds','v29_chronological_folds.csv'],['V29 predictions','v29_all_candidate_predictions.csv'],
 ['V29 selected five','v29_candidate_top5.csv'],['V29 feature evidence','v29_feature_research_catalog.csv'],
];
const metadata=[];
for(const [name,file] of tabs){
  const rows=payload.tables[file]; if(!rows)throw new Error('Missing '+file);
  const keys=[...new Set(rows.flatMap(Object.keys))].filter(k=>!skipNested.has(k));
  const sheet=wb.worksheets.add(name);base(sheet,rows.length+5,Math.max(keys.length,8));
  sheet.getRange('A2').values=[[name]];sheet.getRange('A2').format.font={size:14,bold:true};
  sheet.getRange('A3').values=[[`${rows.length} records | frozen evidence; source: ${file}`]];
  sheet.getRange('A3').format.font={italic:true,color:gray};
  if(keys.length){
    sheet.getRangeByIndexes(4,0,1,keys.length).values=[keys.map(k=>k.replaceAll('_',' '))];
    head(sheet,`A5:${col(keys.length-1)}5`);sheet.getRange(`A5:${col(keys.length-1)}5`).format.rowHeight=42;
    const data=rows.map(r=>keys.map(k=>value(k,r[k])));
    // Apply text formats before values so provider IDs retain their exact digits.
    for(let j=0;j<keys.length;j++) if(data.some(r=>typeof r[j]==='string')) sheet.getRange(`${col(j)}6:${col(j)}${rows.length+5}`).setNumberFormat('@');
    if(data.length)sheet.getRangeByIndexes(5,0,data.length,keys.length).values=data;
    const capacities=[];
    for(let j=0;j<keys.length;j++){
      const c=col(j),k=keys[j];const text=data.map(r=>r[j]).filter(v=>typeof v==='string');
      const longest=Math.max(k.length,...text.map(v=>v.length));
      const width=longest>80?360:Math.min(240,Math.max(85,longest*6.5));
      sheet.getRange(`${c}1:${c}${rows.length+5}`).format.columnWidthPx=width;
      capacities.push(Math.max(12,Math.floor(width/6.5)));
      if(data.some(r=>typeof r[j]==='number'))sheet.getRange(`${c}6:${c}${rows.length+5}`).setNumberFormat(/rate|roi|fraction|probability/.test(k)?'0.0%':/week|rank|count|wins|losses|pushes|^n$|score$|weight|points$|confidence|^page$|^period$|plays|drives|possessions|^shared_/.test(k)?'0':'0.000');
      sheet.getRange(`${c}6:${c}${rows.length+5}`).format.wrapText=true;
      if(text.some(v=>/^\d{4}-\d\d-\d\dT\d\d:/.test(v))){
        const utc=text.every(v=>!/^\d{4}-\d\d-\d\dT/.test(v)||/(Z|\+00:00)$/.test(v));
        sheet.getRange(`${c}6:${c}${rows.length+5}`).setNumberFormat('yyyy-mm-dd"T"hh:mm:ss.000'+(utc?'"Z"':''));
      }
    }
    for(let i=0;i<data.length;i++){
      const lines=Math.max(1,...data[i].map((v,j)=>typeof v==='string'?Math.ceil(v.length/capacities[j]):1));
      sheet.getRangeByIndexes(i+5,0,1,keys.length).format.rowHeight=Math.min(300,24*lines);
    }
    sheet.tables.add(`A5:${col(keys.length-1)}${rows.length+5}`,true,`AuditTable${metadata.length+1}`);
    sheet.freezePanes.freezeRows(5);
  }
  metadata.push({name,file,rows:rows.length,columns:keys.length});
}
// The actual ledger owns the grading calculations. Weights never feed confidence.
const ledger=f.season_contest.ledger;
const headers=['Week','Weight','Game ID','Away','Home','Market','Selection','Side','Contest line','Away score','Home score','Grade margin','W / L / P','Points earned','-110 units','Source PDF','Page','PDF SHA-256','Exact recommendation matches'];
base(actual,56,headers.length);
actual.getRange('A2').values=[['Actual v3 submissions | Weeks 1-10']];actual.getRange('A2').format.font={size:14,bold:true};
actual.getRange('A3').values=[['50 picks; contest weights are scoring allocations. No external Week 11 picks enter these formulas.']];
actual.getRangeByIndexes(4,0,1,headers.length).values=[headers];head(actual,'A5:S5');actual.getRange('A5:S5').format.rowHeight=40;
actual.getRange('C6:C55').setNumberFormat('@');
actual.getRange('A6:B55').format.horizontalAlignment='center';
actual.getRange('A6:S55').values=ledger.map(r=>[r.week,r.contest_weight,r.game_id,r.away,r.home,r.market,r.selection,r.selected_side,r.contest_line,r.away_score,r.home_score,null,null,null,null,r.pdf,r.page,r.pdf_sha256,r.exact_recommendation_cohorts]);
const formulas=ledger.map((r,i)=>{const x=i+6;return [
 `=IF(F${x}="ATS",IF(H${x}="HOME",K${x}-J${x},J${x}-K${x})+I${x},IF(H${x}="OVER",J${x}+K${x}-I${x},I${x}-J${x}-K${x}))`,
 `=IF(L${x}>0,"WIN",IF(L${x}<0,"LOSS","PUSH"))`,
 `=IF(M${x}="WIN",B${x},0)`,`=IF(M${x}="WIN",10/11,IF(M${x}="LOSS",-1,0))`];});
actual.getRange('L6:O55').formulas=formulas;
const widths=[60,65,110,160,160,80,165,75,90,85,85,95,85,95,95,120,60,480,600];
widths.forEach((w,i)=>actual.getRange(`${col(i)}1:${col(i)}55`).format.columnWidthPx=w);
actual.getRange('M6:M55').format.horizontalAlignment='center';
actual.getRange('I6:I55').setNumberFormat('+0.0;-0.0;0.0');actual.getRange('L6:L55').setNumberFormat('+0.0;-0.0;0.0');actual.getRange('O6:O55').setNumberFormat('+0.000;-0.000;0.000');
actual.getRange('M6:M55').conditionalFormats.add('containsText',{text:'LOSS',format:{font:{color:red},fill:'#FBECEE'}});
actual.tables.add('A5:S55',true,'ActualV3Ledger');actual.freezePanes.freezeRows(5);
// A single dashboard carries weekly progression, weight allocation and market splits.
base(dashboard,52,16);dashboard.getRange('A1:P52').format.columnWidthPx=92;
dashboard.getRange('H1:H52').format.columnWidthPx=24;
dashboard.getRange('A2').values=[['2026 CFB | v3 season performance']];dashboard.getRange('A2').format.font={size:16,bold:true};
dashboard.getRange('A3').values=[['Actual Weeks 1-10; Week 11 external submissions excluded by confirmed owner correction.']];dashboard.getRange('A3').format.font={color:gray,italic:true};
dashboard.getRange('A5:F5').values=[['Actual picks','Wins','Losses','Pushes','Points /150','-110 units']];head(dashboard,'A5:F5');
dashboard.getRange('A6:F6').formulas=[['=COUNTA(\'Actual v3 picks\'!C6:C55)','=COUNTIFS(\'Actual v3 picks\'!M6:M55,"WIN")','=COUNTIFS(\'Actual v3 picks\'!M6:M55,"LOSS")','=COUNTIFS(\'Actual v3 picks\'!M6:M55,"PUSH")','=SUM(\'Actual v3 picks\'!N6:N55)','=SUM(\'Actual v3 picks\'!O6:O55)']];
dashboard.getRange('A6:F6').format.font={size:16,bold:true};dashboard.getRange('A6:F6').format.rowHeight=30;dashboard.getRange('F6').setNumberFormat('0.00');
dashboard.getRange('I5:L5').values=[['Week 11 v3 layer','Wins','Losses','Picks']];head(dashboard,'I5:L5');dashboard.getRange('I1:I52').format.columnWidthPx=205;
dashboard.getRange('I6:L10').values=[['Recorded ATS',36,28,64],['Recorded totals',35,29,64],['Friday contextual',2,3,5],['Original combined',3,2,5],['Governed ATS',0,5,5]];
dashboard.getRange('A9:G9').values=[['Week','Wins','Losses','Pushes','Points /15','Units','Cumulative units']];head(dashboard,'A9:G9');dashboard.getRange('A9:G9').format.rowHeight=40;
for(let w=1;w<=10;w++){
 const r=w+9;dashboard.getRange(`A${r}`).values=[[w]];
 dashboard.getRange(`B${r}:G${r}`).formulas=[[
 `=COUNTIFS('Actual v3 picks'!$A$6:$A$55,A${r},'Actual v3 picks'!$M$6:$M$55,"WIN")`,
 `=COUNTIFS('Actual v3 picks'!$A$6:$A$55,A${r},'Actual v3 picks'!$M$6:$M$55,"LOSS")`,
 `=COUNTIFS('Actual v3 picks'!$A$6:$A$55,A${r},'Actual v3 picks'!$M$6:$M$55,"PUSH")`,
 `=SUMIFS('Actual v3 picks'!$N$6:$N$55,'Actual v3 picks'!$A$6:$A$55,A${r})`,
 `=SUMIFS('Actual v3 picks'!$O$6:$O$55,'Actual v3 picks'!$A$6:$A$55,A${r})`,`=SUM(F$10:F${r})`]];
}
dashboard.getRange('F10:G19').setNumberFormat('0.00');
const chart=dashboard.charts.add('line',[dashboard.getRange('A9:A19'),dashboard.getRange('G9:G19')]);
chart.title='Cumulative hypothetical units';chart.titleTextStyle.fontSize=12;chart.titleTextStyle.typeface='Arial';chart.hasLegend=false;
chart.xAxis={axisType:'textAxis',textStyle:{typeface:'Arial',fontSize:10}};chart.yAxis={numberFormatCode:'0.0',numberFormatSourceLinked:false,textStyle:{typeface:'Arial',fontSize:10}};chart.setPosition('I12','P25');
dashboard.getRange('A22:F22').values=[['Weight','Wins','Losses','Picks','Points earned','Available']];head(dashboard,'A22:F22');dashboard.getRange('A22:F22').format.rowHeight=40;
for(let w=1;w<=5;w++){
const r=w+22;dashboard.getRange(`A${r}`).values=[[w]];
dashboard.getRange(`B${r}:F${r}`).formulas=[[
`=COUNTIFS('Actual v3 picks'!$B$6:$B$55,A${r},'Actual v3 picks'!$M$6:$M$55,"WIN")`,
`=COUNTIFS('Actual v3 picks'!$B$6:$B$55,A${r},'Actual v3 picks'!$M$6:$M$55,"LOSS")`,
`=COUNTIFS('Actual v3 picks'!$B$6:$B$55,A${r})`,
`=SUMIFS('Actual v3 picks'!$N$6:$N$55,'Actual v3 picks'!$B$6:$B$55,A${r})`,`=A${r}*D${r}`]];}
dashboard.getRange('A30:F30').values=[['Market','Wins','Losses','Picks','Points earned','Units']];head(dashboard,'A30:F30');dashboard.getRange('A30:F30').format.rowHeight=40;
for(const [i,m] of ['ATS','TOTAL'].entries()){
const r=31+i;dashboard.getRange(`A${r}`).values=[[m]];
dashboard.getRange(`B${r}:F${r}`).formulas=[[
`=COUNTIFS('Actual v3 picks'!$F$6:$F$55,A${r},'Actual v3 picks'!$M$6:$M$55,"WIN")`,
`=COUNTIFS('Actual v3 picks'!$F$6:$F$55,A${r},'Actual v3 picks'!$M$6:$M$55,"LOSS")`,
`=COUNTIFS('Actual v3 picks'!$F$6:$F$55,A${r})`,
`=SUMIFS('Actual v3 picks'!$N$6:$N$55,'Actual v3 picks'!$F$6:$F$55,A${r})`,
`=SUMIFS('Actual v3 picks'!$O$6:$O$55,'Actual v3 picks'!$F$6:$F$55,A${r})`]];}
dashboard.getRange('F31:F32').setNumberFormat('0.00');
dashboard.getRange('A35').values=[['Weights score the contest. They are not calibrated probabilities or model confidence.']];
dashboard.getRange('A37').values=[['Primary defect: governed ATS Top 5 falls through to ID order because uncertainty is null.']];
dashboard.getRange('A39').values=[['Both models trail the locked-line MAE baseline. No replacement has credible Top 5 validation.']];
dashboard.getRange('A41').values=[['Next: prospective market-residual forecasts and out-of-sample calibrated selection ranking.']];
dashboard.getRange('A43').values=[['Week 11: 61 forward-sealed games; three recorded Wednesday games remain late-seal qualified.']];
dashboard.getRange('A45').values=[['Units risk 1 to win 10/11. Contest records are not live sportsbook wagers.']];
base(index,metadata.length+21,5);index.getRange('A1:E70').format.columnWidthPx=250;
index.getRange('A2').values=[['Audit guide and provenance']];index.getRange('A2').format.font={size:14,bold:true};
index.getRange('A4').values=[['All 621 matchups reconcile to ESPN and CFBD finals. All 50 v3 submissions are graded.']];
index.getRange('A6').values=[['Postgame PDFs printed November 16 establish selections, not pregame forecast timestamps.']];
index.getRange('A8').values=[['Original PDF binaries unavailable locally; supplied SHA-256 hashes and source pages retained.']];
index.getRange('A10').values=[['Week 4: 3-2, 8/15; original full-card forecasts missing. Week 5 fifth pick: Texas Tech -13.5.']];
index.getRange('A12').values=[['Week 7 corrected approval matches all five. Historical lines and nine kickoff changes remain separate.']];
index.getRange('A14').values=[['Each cohort is separate. Overlapping submissions and recommendations are never summed as independent picks.']];
index.getRange('A16').values=[['V2.9 experiments are retrospective development. V2.8 remains active. 31 drive anomalies remain quarantined.']];
index.getRange('A18').values=[['Complete narrative: EXECUTIVE_REPORT.md, SEASON_CONTEST_REPORT.md, CONFIDENCE_FORENSICS.md and LESSONS_LEARNED.md.']];
index.getRange('A20:D20').values=[['Worksheet','Source audit CSV','Records','Columns']];head(index,'A20:D20');
index.getRangeByIndexes(20,0,metadata.length,4).values=metadata.map(r=>[r.name,r.file,r.rows,r.columns]);index.getRange(`B21:B${20+metadata.length}`).format.columnWidthPx=380;
// Verification of independent grades and linked recalculation, then restore inputs.
wb.recalculate();
for(let i=0;i<ledger.length;i++){
const x=i+6;const vals=actual.getRange(`L${x}:O${x}`).values[0];
if(Math.abs(vals[0]-ledger[i].grading_margin)>1e-9||vals[1]!==ledger[i].result||vals[2]!==ledger[i].weighted_points||Math.abs(vals[3]-ledger[i].units_minus110)>1e-8)throw new Error(`Independent grade differs at ${x}: ${JSON.stringify(vals)}`);
}
const headline=dashboard.getRange('A6:F6').values[0];
if(JSON.stringify(headline.slice(0,5))!==JSON.stringify([50,20,30,0,55])||Math.abs(headline[5]+130/11)>1e-9)throw new Error('Dashboard mismatch '+headline);
const original=actual.getRange('K6').values[0][0];actual.getRange('K6').values=[[original+1000]];wb.recalculate();
const changed=actual.getRange('M6').values[0][0];
const expectedWins=20-(ledger[0].result==='WIN'?1:0);
if(changed!=='LOSS'||dashboard.getRange('B6').values[0][0]!==expectedWins)throw new Error('Recalculation probe failed: '+JSON.stringify({changed,wins:dashboard.getRange('B6').values,expectedWins}));
actual.getRange('K6').values=[[original]];wb.recalculate();
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},summary:'Formula error scan'});
await fs.mkdir(previewDir,{recursive:true});
await fs.writeFile(path.join(previewDir,'formula-scan.json'),errors.ndjson);
console.log((await wb.inspect({kind:'table',range:'Dashboard!A5:G19',include:'values,formulas',tableMaxRows:15,tableMaxCols:7,maxChars:1800})).ndjson);
for(const name of ['Dashboard','Actual v3 picks','Guide',...tabs.map(r=>r[0])]){
 const preview=await wb.render({sheetName:name,range:name==='Dashboard'?'A1:P46':name==='Guide'?'A1:E24':name==='Actual v3 picks'?'A1:O11':'A1:H11',scale:1,format:'png'});
 await fs.writeFile(path.join(previewDir,name.replaceAll(' ','_')+'.png'),new Uint8Array(await preview.arrayBuffer()));
}
const file=await SpreadsheetFile.exportXlsx(wb);await file.save(output);
await fs.writeFile(path.join(previewDir,'verification.json'),JSON.stringify({headline,rows:50,grade_checks:50,recalculation_probe:'PASS_RESTORED',sheets:metadata.length+3,tables:metadata,output},null,2));
console.log(JSON.stringify({output,sheets:metadata.length+3,headline}));
