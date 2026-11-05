/* Event selection is independent of the UI so boundaries can be regression tested. */
(function(root){
  function selectEvents(bins,scores,threshold=60,prominence=15){
    const result=[],low=Math.max(1,threshold-prominence);
    function emit(a,b){
      let peak=a;for(let i=a+1;i<=b;i++)if(scores[i]>scores[peak])peak=i;
      if(scores[peak]>=threshold)result.push({i:peak,score:scores[peak],start:bins[a].start,end:bins[b].end});
    }
    for(let first=0;first<bins.length;){
      if(bins[first].silence||scores[first]<low){first++;continue}
      let last=first;while(last+1<bins.length&&!bins[last+1].silence&&scores[last+1]>=low)last++;
      // Split two strong peaks at a meaningful valley, regardless of distance.
      // Flat plateaus produce one event; no fixed spacing or top-N suppression.
      let start=first,peak=first,valley=first,falling=false;
      for(let i=first+1;i<=last;i++){
        if(!falling){
          if(scores[i]>=scores[peak]){peak=i;valley=i}
          else if(scores[peak]>=threshold&&scores[peak]-scores[i]>=prominence){falling=true;valley=i}
        }else{
          if(scores[i]<scores[valley])valley=i;
          if(scores[i]>=threshold&&scores[i]-scores[valley]>=prominence){
            emit(start,valley);start=valley+1;peak=i;valley=i;falling=false;
          }
        }
      }
      emit(start,last);first=last+1;
    }
    return result.sort((a,b)=>b.score-a.score||a.start-b.start);
  }
  const api={selectEvents};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.ExcitementEvents=api;
})(typeof globalThis!=='undefined'?globalThis:this);
