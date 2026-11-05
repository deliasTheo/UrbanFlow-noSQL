import java.time.LocalDate;
import fr.urbanflow.unusual.Calendar2024;
class VerifyCalendar2024 {
 public static void main(String[] a) {
  for (String date:new String[]{"2024-03-10","2024-11-03"})
   if (!Calendar2024.transition(LocalDate.parse(date))) throw new AssertionError(date);
  for (String date:new String[]{"2024-03-09","2024-03-11","2024-11-02","2024-11-04"})
   if (Calendar2024.transition(LocalDate.parse(date))) throw new AssertionError(date);
  if (Calendar2024.holiday(LocalDate.of(2024,1,15))==null || Calendar2024.holiday(LocalDate.of(2024,3,10))!=null) throw new AssertionError();
  System.out.println("OK : journées DST complètes, voisins et calendrier férié");
 }
}
