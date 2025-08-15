library(tidyverse)
library(stringr)
options(max.print=1000000)

#####LIST 1: Reformatting/creating a table of the best books of the 21st century, from critics and readers lists, for paper####
#Import unformated book lists
Critics<-read.csv("Import/CriticsList.csv")
Readers<-read.csv("Import/ReadersList.csv")

##Reformat critics list##
Critics<-Critics%>%select(-c(Col4))
#Fill blank values in Col1 with the first non-blank value in the group
Critics1<-Critics%>%
  mutate(Col2=ifelse(Col2=="", NA, Col2)) %>%
  fill(Col2, .direction="down")
#Take the author and rating rows and add to a new column
Critics2<-Critics1 %>%
  group_by(Col2) %>%
  reframe(
    Title = Col3[1],
    Author = Col3[3],
    Rating = Col3[5])

##Reformat result##
#Replace unicode and delete column 2
Critics2<-Critics2%>%
  mutate(across(everything(), ~ str_replace_all(., "\uFFFD", "")))%>%
  select(-c(Col2))
#Delete "Goodreads Author"
Critics2<-Critics2%>%mutate(Author=str_replace_all(Author, "\\(Goodreads Author\\)", ""))
#Separate out rating from number of ratings
Critics2<-Critics2%>%separate(Rating, into=c("Rating", "NumberRatings"), sep=15)
#Delete unneccessary text in rating columns
Critics2<-Critics2%>%mutate(Rating=str_replace_all(Rating, " avg rating", ""))
Critics2<-Critics2%>%mutate(NumberRatings=str_replace_all(NumberRatings, " ratings", ""))
#Put X in new column to denote it was from critics list
Critics2$CriticsList<-"Yes"
Critics2$ReadersList<-""

##Reformat readers list##
Readers<-Readers%>%select(-c(Col4))
#Fill blank values in Col1 with the first non-blank value in the group
Readers1<-Readers%>%
  mutate(Col2=ifelse(Col2=="", NA, Col2)) %>%
  fill(Col2, .direction="down")
#Take the author and rating rows and add to a new column
Readers2<-Readers1 %>%
  group_by(Col2) %>%
  reframe(
    Title = Col3[1],
    Author = Col3[3],
    Rating = Col3[5])

##Reformat result##
#Replace unicode and delete column 2
Readers2<-Readers2%>%
  mutate(across(everything(), ~ str_replace_all(., "\uFFFD", "")))%>%
  select(-c(Col2))
#Delete "Goodreads Author"
Readers2<-Readers2%>%mutate(Author=str_replace_all(Author, "\\(Goodreads Author\\)", ""))
#Separate out rating from number of ratings
Readers2<-Readers2%>%separate(Rating, into=c("Rating", "NumberRatings"), sep=15)
#Delete unneccessary text in rating columns
Readers2<-Readers2%>%mutate(Rating=str_replace_all(Rating, " avg rating", ""))
Readers2<-Readers2%>%mutate(NumberRatings=str_replace_all(NumberRatings, " ratings", ""))
#Put X in new column to denote it was from readers list
Readers2$ReadersList<-"Yes"
Readers2$CriticsList<-""

##Merge two lists##
#rbind
BookList<-bind_rows(Critics2, Readers2)
#Aggregate duplicates
BookList1<-BookList %>%
  group_by(Title) %>%
  summarise(
    CriticsList=ifelse(any(CriticsList=="Yes"), "Yes", NA),
    ReadersList=ifelse(any(ReadersList=="Yes"), "Yes", NA),
    Author=first(Author),
    Rating=first(Rating),
    NumberRatings=first(NumberRatings),
    .groups='drop')
#Reorder columns
BookList1<-BookList1[,c(1,4,5,6,2,3)]
#Add read column
BookList1$Read<-""

##Export##
write.csv(BookList1, "Export/Best100Booksof21stCentury.csv", row.names=FALSE, na="")

#####LIST 2: Reformatting list of awards for app####
#Import awards file
Awards<-read.csv("Import/BookAwards.csv", fileEncoding="latin1", stringsAsFactors=FALSE)
#Reformat
Awards1<-Awards%>%
  mutate(Year=as.character(Year))%>%
  mutate(Result=ifelse(Accolade=="Pulitzer"&Category=="General Nonfiction"&Year=="", "Finalist", 
                       ifelse(Accolade=="Pulitzer"&Category=="General Nonfiction"&!is.na(Year), "Winner", Result)))%>%
  mutate(cond=replace_na(Accolade=="Pulitzer"&Category=="Fiction"&Year=="", FALSE),
         temp_split=if_else(cond, Author, NA_character_))%>%
  separate(temp_split, into = c("Author_new", "Title_new"),
           sep=",", extra="merge", fill="right")%>%
  mutate(Author_new=str_trim(Author_new),
         Title_new=str_trim(Title_new),
         Author=coalesce(Author_new, Author),
         Title=coalesce(Title_new, Title))%>%
  select(-cond, -Author_new, -Title_new)%>%
  mutate(Year=if_else(Year=="",NA_character_, Year))%>%
  fill(Year, .direction="down")%>%
  mutate(Result=if_else(Accolade!="Nobel"&Result=="",NA_character_, Result))%>%
  fill(Result, .direction="down")%>%
  ungroup()

#Reformat book list dataframe for merge with awards dataframe
BookList2<-BookList1%>%
  pivot_longer(cols=c(CriticsList, ReadersList),
               names_to="ListType",
               values_to="HasList")%>%
  filter(HasList=="Yes")%>%
  mutate(Accolade=case_when(
      ListType=="CriticsList" ~ "NYT Critic's Best Books of the 21st Century",
      ListType=="ReadersList" ~ "NYT Reader's Best Books of the 21st Century",
      TRUE ~ NA_character_))%>%
  select(-ListType, -HasList, -Read, -Rating, -NumberRatings)
#Add missing columns
BookList2$Result<-"Listed"
BookList2$Year<-""
BookList2$Category<-""
BookList2$Genres<-""
#Bind
Awards_Lists<-rbind(Awards1, BookList2)
#Import book club file
BookClub<-read.csv("Import/BookClubs.csv", fileEncoding="latin1", stringsAsFactors=FALSE)
#Add missing columns
BookClub$Result<-"Listed"
BookClub$Category<-""
#Remove date column
BookClub<-BookClub%>%select(-c(Date))
#Bind
Awards_Lists_Clubs<-rbind(Awards_Lists, BookClub)
#Clean up
Awards_Lists_Clubs<-Awards_Lists_Clubs%>%filter(Author!="Not awarded")
Awards_Lists_Clubs<-Awards_Lists_Clubs%>%filter(Author!="")
Awards_Lists_Clubs<-Awards_Lists_Clubs%>%select(-c(Genres))
#Export
write.csv(Awards_Lists_Clubs, "Export/Awards_Lists_Clubs.csv", row.names=F)
